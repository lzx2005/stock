# 数据中心第三期实现计划：WebSocket 实时采集 + 盘中半可变层

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **git 约定（2026-08-30）：本计划沿用第二期约定，git 暂缓，不逐任务 commit。** 每完成一步立即勾选 `- [ ]`→`- [x]` 作进度索引（CLAUDE.md 规则），所有 Commit Step 保持 `- [ ]`，待用户说「提交」后一次性整体入库（二期+三期合并）。

**Goal:** 实时行情落地（WebSocket 采集 → Parquet，供回放复盘）+ 盘中查询当日未完成 K 线（半可变层），收盘后由日终任务固化。

**Architecture:** 独立 `ws_collector` 进程：订阅 → 内存环形缓冲 → 定时批量落 `data/realtime/date=YYYY-MM-DD/`。盘中半可变层优先用 REST `klines.intraday` 接口（比 WS 简单可靠）：当日段查询穿透 intraday 接口，60s 内存 TTL 缓存，不落盘；收盘后由第二期日终任务固化。WS 落库数据在日终与 REST 核对，以 REST 为准。

**Tech Stack:** 同前两期 + `websockets`（若 SDK 不暴露 WS）

**Spec:** `docs/superpowers/specs/2026-08-30-data-center-design.md` §4（半可变/实时快照）§7.1
**前置依赖:** 第一、二期计划已完成

---

## 关键设计约定

**半可变层不依赖 WS**：盘中当日 K 线用 REST `klines.intraday`（SDK 已支持 `tf.klines.intraday`）获取 + 60s TTL 内存缓存。理由：回测引擎盘中查询频率低，REST 足够；WS 的价值在 tick 级数据落地回放，两者解耦后 WS 进程挂了不影响查询路径。

**实时表与历史表物理隔离**：`data/realtime/` 独立于 `data/klines/`，格式不同（快照/tick vs K线），不进 `kline_coverage` 体系。当日分钟线"固化"动作 = 日终任务把 REST 分钟线写入 `data/klines/`，WS 数据只做核对源。

**WS 两大未知，Task 1 先探测**：
1. 官方 SDK 是否暴露 WS 接口（skill 文档未提及）——无则按服务商 WS 协议文档用 `websockets` 库直连，需向服务商要 WS 端点/协议文档
2. 推送的数据结构（快照字段、频率、是全推还是增量）

---

### Task 1: WS 能力探测（Spike）

**Files:**
- Create: `scripts/probe_ws.py`
- Modify: `docs/sdk-notes.md`

- [x] **Step 1: 探测 SDK**

```python
"""运行: uv run python scripts/probe_ws.py"""
from tickflow import TickFlow
tf = TickFlow()
print("TickFlow attrs:", [a for a in dir(tf) if not a.startswith("_")])
# 找 ws / stream / subscribe 相关属性
import tickflow
print("tickflow 模块成员:", [a for a in dir(tickflow) if not a.startswith("_")])
# 若发现 ws 入口：尝试订阅 600000.SH，收 10 条消息打印结构
```

同时检查 SDK 包源码：`uv run python -c "import tickflow, os; print(os.path.dirname(tickflow.__file__))"`，grep 包内 `websocket`/`wss` 字样。

- [x] **Step 2: 结论落文档**

`docs/sdk-notes.md` 记录：SDK 有无 WS、端点、鉴权方式、消息结构样例。**若无 WS 支持**，向服务商索取 WS 文档后再继续 Task 2-4；半可变层（Task 5-6）不依赖 WS，可先做。

- [ ] **Step 3: Commit**

```bash
git add scripts/probe_ws.py docs/sdk-notes.md
git commit -m "chore: websocket capability probe"
```

---

### Task 2: RealtimeStore（实时数据落盘）

**Files:**
- Create: `src/datacenter/store/realtime.py`
- Test: `tests/test_realtime_store.py`

- [x] **Step 1: 写失败测试**

```python
import pandas as pd
import pytest
from datacenter.store.realtime import RealtimeStore


@pytest.fixture
def store(tmp_path):
    return RealtimeStore(tmp_path / "realtime")


def test_write_read_roundtrip(store):
    rows = pd.DataFrame([
        {"symbol": "600000.SH", "ts_ms": 1754011800000, "last_price": 10.5,
         "volume": 1000, "turnover": 10500.0, "kind": "snapshot"},
        {"symbol": "600000.SH", "ts_ms": 1754011803000, "last_price": 10.6,
         "volume": 1200, "turnover": 12720.0, "kind": "snapshot"},
    ])
    store.write(rows)
    out = store.read("600000.SH", 1754011800000, 1754011803000)
    assert len(out) == 2
    assert out["ts_ms"].is_monotonic_increasing


def test_partition_by_shanghai_date(store):
    # 北京时间 2025-08-01 09:30 与 15:00 -> 同一 date 分区
    rows = pd.DataFrame([
        {"symbol": "s", "ts_ms": 1754011800000, "last_price": 1.0,
         "volume": 1, "turnover": 1.0, "kind": "snapshot"},
        {"symbol": "s", "ts_ms": 1754031600000, "last_price": 2.0,
         "volume": 2, "turnover": 2.0, "kind": "snapshot"},
    ])
    written = store.write(rows)
    assert len(written) == 1
    assert "date=2025-08-01" in str(written[0])


def test_read_empty(store):
    assert store.read("x.SH", 0, 10**13).empty
```

- [x] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**

实现要点：与 KlineStore 同模式（临时文件 → 原子 rename → DuckDB 读），分区为 `date=YYYY-MM-DD`（Asia/Shanghai），文件 `rt-{HHMMSSffffff}.parquet`；列：`symbol, ts_ms, last_price, volume, turnover, kind`（kind: snapshot/tick，按 Task 1 探测的实际消息结构调整）。

- [ ] **Step 5: Commit**

```bash
git add src/datacenter/store/realtime.py tests/test_realtime_store.py
git commit -m "feat: RealtimeStore date-partitioned parquet"
```

---

### Task 3: WS 采集器核心（缓冲 + 批量落盘）

**Files:**
- Create: `src/datacenter/jobs/ws_collector.py`
- Test: `tests/test_ws_collector.py`

- [x] **Step 1: 写失败测试**

与传输解耦设计：`Collector(store, flush_interval=5.0, flush_count=1000, clock=...)` 暴露 `on_message(dict)` 与 `flush()`；WS 连接层只负责把消息转成 dict 喂给 `on_message`。测试全在内存完成：

```python
def test_buffer_flushes_at_count(tmp_path):
    store = RealtimeStore(tmp_path / "realtime")
    c = Collector(store, flush_interval=3600, flush_count=3)
    for i in range(3):
        c.on_message({"symbol": "s", "ts_ms": i, "last_price": 1.0,
                      "volume": 1, "turnover": 1.0})
    assert len(store.read("s", 0, 10)) == 3  # 满 3 条自动落盘


def test_buffer_flushes_on_timer(tmp_path):
    store = RealtimeStore(tmp_path / "realtime")
    c = Collector(store, flush_interval=5.0, flush_count=1000)
    c.on_message({"symbol": "s", "ts_ms": 1, "last_price": 1.0, "volume": 1, "turnover": 1.0})
    c.maybe_flush(now=6.0)  # 超过间隔
    assert len(store.read("s", 0, 10)) == 1


def test_malformed_message_dropped_with_log(tmp_path, caplog):
    store = RealtimeStore(tmp_path / "realtime")
    c = Collector(store)
    c.on_message({"garbage": True})  # 缺字段不崩溃
    assert store.read("s", 0, 10).empty
```

- [x] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**

实现要点：

```python
class Collector:
    """WS 消息缓冲器：满 flush_count 条或距上次落盘超 flush_interval 秒即批量写盘。"""
    def __init__(self, store, flush_interval=5.0, flush_count=1000, now=time.monotonic):
        ...
    def on_message(self, msg: dict) -> None:
        # 校验必需字段 symbol/ts_ms/last_price，缺则记日志丢弃
        # 附加 kind 字段后入缓冲；满 flush_count 立即 flush()
    def maybe_flush(self, now=None) -> None: ...
    def flush(self) -> None: ...
```

- [ ] **Step 5: Commit**

```bash
git add src/datacenter/jobs/ws_collector.py tests/test_ws_collector.py
git commit -m "feat: ws collector buffering core"
```

---

### Task 4: WS 连接层 + 采集进程入口

**Files:**
- Modify: `src/datacenter/jobs/ws_collector.py`（加 `run_collector`）
- Create: `scripts/ws_collect.py`

- [x] **Step 1: 实现连接层**

```python
async def run_collector(symbols, store, reconnect_max=10):
    """断线指数退避重连（1s,2s,4s...封顶 60s），重连后自动重订阅。
    连接形态以 Task 1 探测结论为准：
    - SDK 有 WS: 用 SDK 接口订阅
    - 无: websockets.connect(wss_url, extra_headers={"Authorization": key})，按服务商协议发订阅帧
    """
```

连接层不写单测（真网络依赖），用 spike 验证：盘中跑 5 分钟，检查 `data/realtime/date=<今天>/` 有文件、行数增长、字段齐全。

- [x] **Step 2: 写进程入口**

`scripts/ws_collect.py`：CLI 参数 `--universe CN_Equity_A`（默认）或 `--symbols a.SH,b.SH`；`asyncio.run(run_collector(...))`；SIGINT 优雅退出（退出前 flush）；日志到 stdout + `data/ws_collector.log`。

- [ ] **Step 3: 盘中真实验证（spike）**（权限阻塞：NO_WS_PERMISSION，见 sdk-notes.md §11）

交易时段运行 5 分钟，验证落盘与行数增长；记录消息速率（条/秒）到 `docs/sdk-notes.md`，据此校准 `flush_count/flush_interval` 默认值。

- [ ] **Step 4: Commit**

```bash
git add src/datacenter/jobs/ws_collector.py scripts/ws_collect.py
git commit -m "feat: ws collector process with reconnect"
```

---

### Task 5: 盘中半可变层（intraday TTL 缓存）

**Files:**
- Modify: `src/datacenter/api.py`
- Modify: `src/datacenter/client/tickflow_client.py`（get_intraday）
- Create: `src/datacenter/intraday.py`
- Test: `tests/test_intraday.py`

- [x] **Step 1: 写失败测试**

前置准备（本任务内一并做）：
- conftest.py 把 `FakeClock` 从 `test_ratelimit.py` 提升为共享 fixture 工具类
- `FakeKlines` 增加 `intraday` 方法：`self.intraday_df = pd.DataFrame()` 默认空；`intraday(symbol, period="1m", as_dataframe=True)` 返回 `self.intraday_df`——与 client 调用路径 `tf.klines.intraday` 一致
- `DataCenter.__init__` 增加 `now_ms: Callable[[], int] | None = None`（默认真实时间），供测试注入"今日"

```python
def test_intraday_cached_within_ttl():
    cache = IntradayCache(ttl_sec=60)
    calls = []
    def fetch():
        calls.append(1)
        return make_kline_df("600000.SH", T0, 3, 60_000)
    cache.get_or_fetch("600000.SH", "1m", fetch)
    cache.get_or_fetch("600000.SH", "1m", fetch)
    assert len(calls) == 1  # TTL 内不重复请求


def test_intraday_refetch_after_ttl():
    clock = FakeClock()
    cache = IntradayCache(ttl_sec=60, now=clock.now)
    calls = []
    def fetch():
        calls.append(1)
        return make_kline_df("600000.SH", T0, 3, 60_000)
    cache.get_or_fetch("600000.SH", "1m", fetch)
    clock.t += 61
    cache.get_or_fetch("600000.SH", "1m", fetch)
    assert len(calls) == 2


def test_get_klines_intraday_day_uses_intraday_api(tmp_path):
    """end_ms 落在今日（时钟注入）-> 当日段走 intraday 接口，且不记永久 coverage。"""
    fake = FakeTickFlow(symbols=["600000.SH"])
    now = T0 + 4 * 3600_000  # 当日 13:30（T0 为 09:30）
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake, now_ms=lambda: now)
    fake.klines.intraday_df = make_kline_df("600000.SH", T0, 3, 60_000)  # 今日 3 根 1m
    df = dc.get_klines("600000.SH", "1m", T0 - 10 * DAY, now)
    # 历史 1m 无覆盖 -> 回源得空（FakeKlines 队列空返回空 df）；当日段来自 intraday
    assert len(df) == 3
    assert df["timestamp"].min() >= T0
    # 当日段不得记入永久覆盖区间（否则明日查询会误判今日已缓存）
    cov = dc.meta.get_coverage("600000.SH", "1m")
    assert cov is None or cov[1] < T0
```

- [x] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**

实现要点：

`intraday.py`：

```python
class IntradayCache:
    """盘中当日数据 TTL 缓存（纯内存，不落盘——收盘后由日终任务固化）。"""
    def __init__(self, ttl_sec=60, now=time.monotonic):
        self._ttl, self._now = ttl_sec, now
        self._cache: dict[tuple[str, str], tuple[float, pd.DataFrame]] = {}

    def get_or_fetch(self, symbol, period, fetch):
        key = (symbol, period)
        hit = self._cache.get(key)
        if hit and self._now() - hit[0] < self._ttl:
            return hit[1]
        df = fetch()
        self._cache[key] = (self._now(), df)
        return df
```

`client.get_intraday(symbol, period)` → `self._call(self._tf.klines.intraday, symbol, period=period, as_dataframe=True)`，输出标准化为 KLINE_COLUMNS（加 symbol 列）。

`api.get_klines` 融合逻辑：

```python
        # 当日段判定：end_ms 超过北京今日 0 点 -> 当日部分走 intraday
        # now_ms 可注入（__init__ 参数），测试用合成时间戳时不受真实日期影响
        SH_OFFSET_MS = 8 * 3600_000
        now = self._now_ms()
        today_start = now - ((now + SH_OFFSET_MS) % 86_400_000)
        if end_ms >= today_start and period in MINUTE_PERIODS | {"1d"}:
            hist_end = min(end_ms, today_start - 1)
            hist = 历史部分(原 resolver 路径, start_ms..hist_end)  # coverage 只扩展到 hist_end
            intra = self.intraday.get_or_fetch(symbol, period,
                    lambda: self.client.get_intraday(symbol, period))
            intra = intra[intra["timestamp"] >= max(start_ms, today_start)]
            df = pd.concat([hist, intra]).drop_duplicates("timestamp", keep="last")
```

注意：历史 coverage 只扩展到昨日——`resolver.ensure` 的 end_ms 须截到 `today_start - 1`，**绝不把"当日已解析"记入永久覆盖区间**（否则明日查询会误判今日已缓存）。这是本任务最易错的点，注释写明，测试 `test_get_klines_intraday_day_uses_intraday_api` 的 coverage 断言专门防这个回归。

- [ ] **Step 5: Commit**

```bash
git add src/datacenter/intraday.py src/datacenter/api.py src/datacenter/client/tickflow_client.py tests/test_intraday.py
git commit -m "feat: intraday semi-mutable layer with TTL cache"
```

---

### Task 6: 日终固化集成 + WS/REST 核对

**Files:**
- Modify: `src/datacenter/jobs/daily_maintenance.py`
- Test: `tests/test_daily_maintenance.py` 追加

- [x] **Step 1: 写失败测试**

```python
def test_daily_solidifies_minute_klines(tmp_path):
    """日终把当日各分钟周期从 REST 拉下写入 klines/，coverage 扩展到今日。"""
    fake = FakeTickFlow(symbols=["a.SH"])
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    dc.list_symbols()
    dc.meta.extend_coverage("a.SH", "1m", T0 - 30 * DAY, T0 - 1)  # 历史已覆盖到昨日
    fake.klines.queue(make_kline_df("a.SH", T0, 10, 60_000))      # 当日 10 根 1m
    report = run_daily_maintenance(dc, today_ms=T0 + 5 * 3600_000, periods=["1m"])
    assert report["symbols_updated"] >= 1
    df = dc.klines.read(["a.SH"], "1m", T0, T0 + 5 * 3600_000)
    assert len(df) == 10
    assert dc.meta.get_coverage("a.SH", "1m")[1] >= T0 + 5 * 3600_000


def test_ws_rest_reconciliation(tmp_path):
    """realtime/ 有当日快照时，日终把 WS 聚合的 1m 与 REST 1m 比对，差异写入报告。"""
    fake = FakeTickFlow(symbols=["a.SH"])
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    dc.list_symbols()
    # REST 当日 2 根 1m：close = base+0.5, volume=1000/根
    fake.klines.queue(make_kline_df("a.SH", T0, 2, 60_000))
    # WS 快照：每根 1m 窗口内 2 条快照，末条价=close；第 2 根 volume 与 REST 差 50%
    snaps = pd.DataFrame([
        {"symbol": "a.SH", "ts_ms": T0 + 1000, "last_price": ..., "volume": 500, "turnover": ..., "kind": "snapshot"},
        {"symbol": "a.SH", "ts_ms": T0 + 59_000, "last_price": ..., "volume": 1000, ...},
        {"symbol": "a.SH", "ts_ms": T0 + 61_000, ..., "volume": 1100, ...},
        {"symbol": "a.SH", "ts_ms": T0 + 119_000, ..., "volume": 1500, ...},  # 聚合 vol=500 vs REST 1000
    ])
    dc.realtime.write(snaps)
    report = run_daily_maintenance(dc, today_ms=T0 + 5 * 3600_000, periods=["1m"])
    assert report["reconcile_mismatches"]  # 第 2 根 volume 差异 >1% 被报出
```

（快照聚合规则：每分钟窗口首条 last_price=open、末条=close、max/min=high/low、volume 取窗口差分。实现时把 `...` 按 FakeKlines 生成的价格补全。）

- [x] **Step 2~4: 实现并通过**（真实分钟回源仍被 klines.get(1m) 无权限阻塞，见 sdk-notes.md §2；逻辑经 fake 单测+当日段真实 intraday smoke 验证）

实现要点：
- `run_daily_maintenance` 加 `periods` 参数（默认 `["1d", "1m"]`），分钟周期同样走"覆盖缺口回源"逻辑固化
- 核对：`realtime` 当日快照按分钟聚合（每分钟末条 last_price=close，首条 open，max/min 得 high/low，volume 差分）→ 与 REST 1m 对比 close/volume，容差 1%，差异列表进 `job_reports`
- 不一致**以 REST 为准**（REST 数据已写入 klines/，WS 数据留在 realtime/ 不动）

- [ ] **Step 5: Commit**

```bash
git add src/datacenter/jobs/daily_maintenance.py tests/test_daily_maintenance.py
git commit -m "feat: daily solidification of intraday klines + WS/REST reconciliation"
```

---

### Task 7: README + 全量回归

- [x] **Step 1: README 补充**：WS 采集启动命令、盘中查询行为说明（当日数据 TTL 60s）、realtime 数据回放读取示例
- [x] **Step 2: `uv run pytest` 全量回归**
- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: phase 3 usage (ws collector, intraday layer, replay)"
```

---

## 完成标准（第三期 DoD）

1. WS 进程盘中稳定运行 ≥ 1 小时，断线自动重连，数据落盘可查
2. 盘中 `get_klines(..., end_ms=现在)` 返回含当日数据，TTL 内零重复请求
3. 日终任务后当日分钟线固化进历史层，WS/REST 差异有报告
4. 测试全绿
