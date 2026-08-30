# 数据中心第一期实现计划：K线缓存 + 历史回填

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建"本地优先、缺失回源、查到即存"的 A 股 K 线数据中心，并完成全市场 3 年 × 11 周期的历史回填能力。

**Architecture:** 库模式。门面 `DataCenter` → `CacheResolver`（覆盖区间判断）→ `KlineStore`（Parquet 分区 + DuckDB 查询）/ `MetaStore`（SQLite 覆盖区间与任务进度）→ `TickFlowClient`（官方 SDK 薄封装：限速 + 重试 + 分页）。存储原始价（adjust=none），复权留给第二期。

**Tech Stack:** Python 3.11+、uv、tickflow[all]（官方 SDK）、DuckDB、pandas、pyarrow、SQLite（stdlib）、pytest

**Spec:** `docs/superpowers/specs/2026-08-30-data-center-design.md`（本计划只覆盖其"第一期"；财务缓存/复权/校验为第二期，WS 实时为第三期）

---

## 关键设计约定（所有任务共享）

**K 线 Parquet 列**：`symbol`(str), `timestamp`(int64, 毫秒), `open`, `high`, `low`, `close` (float64), `volume`(int64), `amount`(float64)。只存原始价。

**分区规则**：
- 分钟周期（`1m/5m/10m/15m/30m/60m`）：`data/klines/period={period}/year={yyyy}/month={mm}/`
- 日线及更粗（`1d/1w/1M/1Q/1Y`）：`data/klines/period={period}/year={yyyy}/`
- year/month 按 **Asia/Shanghai** 时区从 timestamp 推导（A 股交易时间按北京时间归属）
- 文件名 `part-{yyyymmddHHMMSSffffff}-{tag}.parquet`：**时间戳在文件名最前**，保证字典序=写入序，读取去重时"后写胜出"（tag 在后会主导字典序，会破坏该语义——已按审查修正）

**coverage 语义**：`kline_coverage` 的区间 `[start_ms, end_ms]` 表示"**已向数据源请求并解析过**的范围"，不是"有数据的范围"。对未上市/停牌导致的空区间，同样标记覆盖——否则每次查询都会重复回源打空。区间只连续扩展，区内小洞留给第二期校验任务处理。

**常量**：

```python
ALL_PERIODS = ["1m", "5m", "10m", "15m", "30m", "60m", "1d", "1w", "1M", "1Q", "1Y"]
MINUTE_PERIODS = {"1m", "5m", "15m", "30m", "60m"}  # 套餐不含 10m；10m 需要时由 5m 聚合
BACKFILL_ORDER = ["1d", "1w", "1M", "1Q", "1Y", "60m", "30m", "15m", "5m", "1m"]  # 先粗后细
MAX_PAGE = 5000  # 分钟接口单次上限 5000 条（日线文档上限 10000，统一取保守值）
MINUTE_HISTORY_DAYS = 365   # 套餐硬限制：分钟线仅最近 365 天
DAILY_HISTORY_DAYS = 3 * 365
```

**套餐限流（已实测+确认，据此设定 client 默认速率）**：日线按只 120 次/分、批量 60 次/分 ×200 标的；分钟按只 60 次/分、批量 30 次/分 ×100 标的；单次上限 5000 条；分钟线仅最近 365 天。**非法 symbol 不抛异常、返回空 DataFrame**；SDK 异常类在 `tickflow._exceptions`（RateLimitError/APIError/PermissionError/ConnectionError/TimeoutError 等，注意遮蔽内置同名类，导入需模块前缀）。**回填必须用批量接口**：分钟线逐只分页需 ~28 小时，批量按时间窗只需 ~35 分钟。

**目录结构**：

```
stock/
├── pyproject.toml
├── .gitignore                  # 已存在（含 data/）
├── src/datacenter/
│   ├── __init__.py             # 导出 DataCenter
│   ├── constants.py            # 上方常量
│   ├── exceptions.py           # 异常体系
│   ├── client/__init__.py
│   ├── client/ratelimit.py     # TokenBucket
│   ├── client/tickflow_client.py
│   ├── store/__init__.py
│   ├── store/meta.py           # MetaStore (SQLite)
│   ├── store/klines.py         # KlineStore (Parquet/DuckDB)
│   ├── resolver.py             # CacheResolver
│   ├── api.py                  # DataCenter 门面
│   └── jobs/__init__.py
│   └── jobs/backfill.py
├── scripts/probe_sdk.py        # 一次性 SDK 探测（Task 1）
└── tests/
    ├── conftest.py             # tmp 数据目录、FakeTickFlow、合成K线生成器
    ├── test_ratelimit.py
    ├── test_tickflow_client.py
    ├── test_meta.py
    ├── test_kline_store.py
    ├── test_resolver.py
    ├── test_api.py
    └── test_backfill.py
```

---

### Task 1: 项目骨架 + git 初始化 + SDK 探测

**Files:**
- Create: `pyproject.toml`
- Create: `src/datacenter/__init__.py`（空）
- Create: `scripts/probe_sdk.py`

- [x] **Step 1: 初始化 git 与项目骨架**

```bash
cd <项目根目录>
git init
git add .gitignore docs/
git commit -m "chore: initial docs and gitignore"
mkdir -p src/datacenter/client src/datacenter/store src/datacenter/jobs tests scripts
touch src/datacenter/__init__.py src/datacenter/client/__init__.py src/datacenter/store/__init__.py src/datacenter/jobs/__init__.py tests/__init__.py
```

- [x] **Step 2: 写 pyproject.toml**

```toml
[project]
name = "datacenter"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "tickflow[all]>=0.1.17",
    "duckdb>=1.1",
    "pandas>=2.2",
    "pyarrow>=17",
]

[dependency-groups]
dev = ["pytest>=8", "pytest-timeout>=2.3"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/datacenter"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --timeout=60"
```

Run: `uv sync` — 预期成功创建 `.venv` 并安装依赖。

- [x] **Step 3: 写 SDK 探测脚本**

`scripts/probe_sdk.py`：

```python
"""一次性探测脚本：确认 tickflow SDK 的真实行为（字段、异常、分页）。
运行: uv run python scripts/probe_sdk.py
"""
import time
import traceback
from tickflow import TickFlow

tf = TickFlow()  # 读取环境变量 TICKFLOW_API_KEY

print("=== 1. 正常日K查询 ===")
df = tf.klines.get("600000.SH", period="1d", count=5, adjust="none", as_dataframe=True)
print(type(df), df.columns.tolist() if hasattr(df, "columns") else "")
print(df)

print("\n=== 2. 带时间范围的分钟K（验证 start_time/end_time 生效）===")
end_ms = int(time.time() * 1000)
start_ms = end_ms - 3 * 24 * 3600 * 1000
df2 = tf.klines.get("600000.SH", period="1m", start_time=start_ms, end_time=end_ms,
                    count=100, adjust="none", as_dataframe=True)
print(f"rows={len(df2)}")
if hasattr(df2, "columns") and len(df2):
    print("ts range:", df2["timestamp"].min(), "->", df2["timestamp"].max())

print("\n=== 3. 非法 symbol 的异常类型 ===")
try:
    tf.klines.get("INVALID.XX", period="1d", count=5)
except Exception as e:
    print("exception class:", type(e).__module__, type(e).__qualname__)
    print("args:", e.args)
    print("str:", str(e)[:300])

print("\n=== 4. 标的池 ===")
uni = tf.universes.get("CN_Equity_A")
print(type(uni), list(uni.keys()) if isinstance(uni, dict) else "")
symbols = uni["symbols"] if isinstance(uni, dict) else uni
print("A股标的数:", len(symbols), "示例:", symbols[:5])

print("\n=== 5. 限流信号探测（快速连发30次看是否报错）===")
errs = 0
for i in range(30):
    try:
        tf.klines.get("600000.SH", period="1d", count=1)
    except Exception as e:
        errs += 1
        print(f"  第{i+1}次触发异常: {type(e).__qualname__}: {str(e)[:200]}")
        break
print(f"完成, 异常数={errs}（0 说明 30 次连发未触限）")
```

- [x] **Step 4: 运行探测并记录结果**

Run: `uv run python scripts/probe_sdk.py`

记录到 `docs/sdk-notes.md`：K线返回的真实列名与 dtype、异常类层次（Task 3 的 `classify_error` 据此调整）、标的池大小、限流迹象。**若 `klines.get` 的参数名或返回结构与脚本假设不符，修正脚本重跑，并更新后续任务中的调用签名。**

- [x] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/ scripts/ docs/sdk-notes.md
git commit -m "chore: project skeleton + SDK probe notes"
```

---

### Task 2: 异常体系 + TokenBucket 限速器

**Files:**
- Create: `src/datacenter/exceptions.py`
- Create: `src/datacenter/constants.py`
- Create: `src/datacenter/client/ratelimit.py`
- Test: `tests/test_ratelimit.py`

- [x] **Step 1: 写失败测试**

`tests/test_ratelimit.py`：

```python
from datacenter.client.ratelimit import TokenBucket


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.slept = []
    def now(self):
        return self.t
    def sleep(self, secs):
        self.slept.append(secs)
        self.t += secs


def test_tokens_available_immediately_up_to_capacity():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_sec=10, now=clock.now, sleep=clock.sleep)
    for _ in range(10):  # 容量=1秒的速率，10 个立即可用
        bucket.acquire()
    assert clock.slept == []


def test_acquire_blocks_when_empty():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_sec=10, now=clock.now, sleep=clock.sleep)
    for _ in range(10):
        bucket.acquire()
    bucket.acquire()  # 第 11 个要等 0.1s
    assert clock.slept == [0.1]


def test_tokens_refill_over_time():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_sec=10, now=clock.now, sleep=clock.sleep)
    for _ in range(10):
        bucket.acquire()
    clock.t += 0.5  # 过了半秒，补 5 个
    for _ in range(5):
        bucket.acquire()
    assert clock.slept == []
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_ratelimit.py -v`
Expected: FAIL（`ModuleNotFoundError: datacenter.client.ratelimit`）

- [x] **Step 3: 实现**

`src/datacenter/exceptions.py`：

```python
class DataCenterError(Exception):
    """数据中心异常基类"""


class DataUnavailableError(DataCenterError):
    """本地无数据且回源失败"""


class TickFlowError(DataCenterError):
    """数据源调用失败（重试耗尽或不可重试错误）"""


class RateLimitError(TickFlowError):
    """数据源限流（重试耗尽后抛出）"""
```

`src/datacenter/constants.py`：把"关键设计约定"里的 `ALL_PERIODS / MINUTE_PERIODS / BACKFILL_ORDER / MAX_PAGE` 写进去。

`src/datacenter/client/ratelimit.py`：

```python
import threading
import time


class TokenBucket:
    """线程安全令牌桶。容量 = 1 秒的速率（burst 上限）。"""

    def __init__(self, rate_per_sec: float, now=time.monotonic, sleep=time.sleep):
        self._rate = rate_per_sec
        self._capacity = rate_per_sec
        self._tokens = rate_per_sec
        self._last = now()
        self._now = now
        self._sleep = sleep
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._now()
                self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            self._sleep(wait)
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_ratelimit.py -v`
Expected: 3 passed

- [x] **Step 5: Commit**

```bash
git add src/datacenter/exceptions.py src/datacenter/constants.py src/datacenter/client/ratelimit.py tests/test_ratelimit.py
git commit -m "feat: exception hierarchy + thread-safe token bucket"
```

---

### Task 3: TickFlowClient（SDK 薄封装：错误分类 + 重试 + K线分页）

**Files:**
- Create: `src/datacenter/client/tickflow_client.py`
- Test: `tests/test_tickflow_client.py`
- Test: `tests/conftest.py`

- [x] **Step 1: 写 conftest 与失败测试**

`tests/conftest.py`：

```python
import pandas as pd
import pytest


def make_kline_df(symbol: str, start_ms: int, n: int, step_ms: int) -> pd.DataFrame:
    """确定性合成 K 线：价格由 start_ms 决定，便于断言。"""
    ts = [start_ms + i * step_ms for i in range(n)]
    base = (start_ms // 1000) % 100 + 10.0
    return pd.DataFrame({
        "symbol": symbol,
        "timestamp": ts,
        "open": [base] * n,
        "high": [base + 1] * n,
        "low": [base - 1] * n,
        "close": [base + 0.5] * n,
        "volume": [1000] * n,
        "amount": [base * 1000] * n,
    })


class FakeKlines:
    """模拟 tf.klines：按调用次数返回预设结果或抛异常。"""
    def __init__(self):
        self.calls = []
        self.script = []  # 每项: DataFrame | Exception

    def queue(self, item):
        self.script.append(item)

    def get(self, symbol, period="1d", count=None, start_time=None, end_time=None,
            adjust=None, as_dataframe=False):
        self.calls.append(dict(symbol=symbol, period=period, count=count,
                               start_time=start_time, end_time=end_time, adjust=adjust))
        item = self.script.pop(0) if self.script else pd.DataFrame()
        if isinstance(item, Exception):
            raise item
        return item


class FakeUniverses:
    def __init__(self, symbols):
        self._symbols = symbols
    def get(self, universe_id):
        return {"id": universe_id, "symbols": self._symbols}


class FakeTickFlow:
    def __init__(self, symbols=None):
        self.klines = FakeKlines()
        self.universes = FakeUniverses(symbols or [])


@pytest.fixture
def fake_tf():
    return FakeTickFlow(symbols=["600000.SH", "000001.SZ"])


@pytest.fixture
def tmp_data_dir(tmp_path):
    return tmp_path / "data"
```

`tests/test_tickflow_client.py`：

```python
import pandas as pd
import pytest

from datacenter.client.tickflow_client import TickFlowClient
from datacenter.exceptions import RateLimitError, TickFlowError
from tests.conftest import make_kline_df


def make_client(fake_tf, **kw):
    return TickFlowClient(tf=fake_tf, rate_per_sec=1000, max_retries=2,
                          sleep=lambda s: None, **kw)


def test_retry_on_rate_limit_then_success(fake_tf):
    df = make_kline_df("600000.SH", 1000, 3, 1000)
    fake_tf.klines.queue(Exception("429 too many requests"))
    fake_tf.klines.queue(df)
    client = make_client(fake_tf)
    out = client.get_klines_range("600000.SH", "1d", 1000, 4000)
    assert len(out) == 3
    assert len(fake_tf.klines.calls) == 2  # 重试了一次


def test_rate_limit_exhausted_raises(fake_tf):
    for _ in range(3):
        fake_tf.klines.queue(Exception("rate limit exceeded"))
    client = make_client(fake_tf)
    with pytest.raises(RateLimitError):
        client.get_klines_range("600000.SH", "1d", 1000, 4000)


def test_client_error_not_retried(fake_tf):
    fake_tf.klines.queue(Exception("INVALID_PERIOD: 2d"))
    client = make_client(fake_tf)
    with pytest.raises(TickFlowError) as exc_info:
        client.get_klines_range("600000.SH", "1d", 1000, 4000)
    assert not isinstance(exc_info.value, RateLimitError)
    assert len(fake_tf.klines.calls) == 1  # 不重试


def test_pagination_accumulates_until_short_page(fake_tf):
    # 第一页满 MAX_PAGE(5000) -> 继续；第二页不足 -> 停止
    page1 = make_kline_df("600000.SH", 0, 5000, 60_000)
    page2 = make_kline_df("600000.SH", 5000 * 60_000, 50, 60_000)
    fake_tf.klines.queue(page1)
    fake_tf.klines.queue(page2)
    client = make_client(fake_tf)
    out = client.get_klines_range("600000.SH", "1m", 0, 10**13)
    assert len(out) == 5050
    assert len(fake_tf.klines.calls) == 2
    # 第二页的 start_time 接续第一页最大时间戳
    assert fake_tf.klines.calls[1]["start_time"] == page1["timestamp"].max() + 1


def test_empty_result_returns_empty_df(fake_tf):
    fake_tf.klines.queue(pd.DataFrame())
    client = make_client(fake_tf)
    out = client.get_klines_range("600000.SH", "1d", 1000, 4000)
    assert out.empty
    assert list(out.columns) == ["symbol", "timestamp", "open", "high", "low",
                                 "close", "volume", "amount"]


def test_list_universe_symbols(fake_tf):
    client = make_client(fake_tf)
    assert client.list_universe_symbols("CN_Equity_A") == ["600000.SH", "000001.SZ"]
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_tickflow_client.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 实现**

`src/datacenter/client/tickflow_client.py`：

```python
import random
import time

import pandas as pd
from tickflow import TickFlow

from datacenter.constants import MAX_PAGE
from datacenter.exceptions import RateLimitError, TickFlowError
from datacenter.client.ratelimit import TokenBucket

KLINE_COLUMNS = ["symbol", "timestamp", "open", "high", "low", "close", "volume", "amount"]


def classify_error(exc: Exception) -> str:
    """返回 rate_limit / client / server。优先按 SDK 异常类判断（实测确认），字符串兜底。
    注意 SDK 的 PermissionError/ConnectionError/TimeoutError 遮蔽内置同名类，必须模块前缀导入。"""
    try:
        from tickflow import _exceptions as tfe
        if isinstance(exc, tfe.RateLimitError):
            return "rate_limit"
        if isinstance(exc, (tfe.BadRequestError, tfe.NotFoundError, tfe.PermissionError,
                            tfe.AuthenticationError)):
            return "client"
        if isinstance(exc, (tfe.InternalServerError, tfe.ConnectionError, tfe.TimeoutError)):
            return "server"
    except ImportError:
        pass
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "too many" in msg:
        return "rate_limit"
    if "invalid" in msg or "not found" in msg or "400" in msg or "404" in msg:
        return "client"
    return "server"


def empty_klines() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in {
        "symbol": "object", "timestamp": "int64", "open": "float64", "high": "float64",
        "low": "float64", "close": "float64", "volume": "int64", "amount": "float64",
    }.items()})


class TickFlowClient:
    """官方 SDK 薄封装：限速 + 重试 + K线分页。只负责"取数"，不管缓存。"""

    def __init__(self, tf: TickFlow | None = None, rate_per_sec: float = 10.0,
                 max_retries: int = 3, sleep=time.sleep):
        self._tf = tf or TickFlow()
        self._bucket = TokenBucket(rate_per_sec)
        self._max_retries = max_retries
        self._sleep = sleep

    def _call(self, fn, *args, **kwargs):
        last_exc = None
        for attempt in range(self._max_retries + 1):
            self._bucket.acquire()
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                kind = classify_error(exc)
                if kind == "client" or attempt == self._max_retries:
                    break
                backoff = (2 ** attempt) * (2.0 if kind == "rate_limit" else 0.5)
                self._sleep(backoff + random.uniform(0, 0.3))
        if classify_error(last_exc) == "rate_limit":
            raise RateLimitError(str(last_exc)) from last_exc
        raise TickFlowError(str(last_exc)) from last_exc

    def get_klines_range(self, symbol: str, period: str,
                         start_ms: int, end_ms: int) -> pd.DataFrame:
        """分页拉取 [start_ms, end_ms] 的原始价 K 线，返回标准列 DataFrame。"""
        frames, cursor = [], start_ms
        while True:
            df = self._call(self._tf.klines.get, symbol, period=period, count=MAX_PAGE,
                            start_time=cursor, end_time=end_ms,
                            adjust="none", as_dataframe=True)
            if df is None or df.empty:
                break
            df = df.copy()
            df["symbol"] = symbol
            frames.append(df)
            last_ts = int(df["timestamp"].max())
            if len(df) < MAX_PAGE or last_ts >= end_ms:
                break
            cursor = last_ts + 1
        if not frames:
            return empty_klines()
        out = pd.concat(frames, ignore_index=True)
        out = out.drop_duplicates(subset=["symbol", "timestamp"]).sort_values("timestamp")
        for col in KLINE_COLUMNS:
            if col not in out.columns:
                out[col] = pd.NA
        return out[KLINE_COLUMNS].reset_index(drop=True)

    def list_universe_symbols(self, universe_id: str) -> list[str]:
        uni = self._call(self._tf.universes.get, universe_id)
        return list(uni["symbols"] if isinstance(uni, dict) else uni)

    def get_klines_batch_range(self, symbols: list[str], period: str,
                               start_ms: int, end_ms: int) -> pd.DataFrame:
        """批量拉取（回填主力路径）。底层 tf.klines.batch 一次最多 100/200 标的、
        每标的最多 MAX_PAGE 条；满页的标的从各自 last_ts+1 续拉，直到全部不足页。
        返回合并后的标准列 DataFrame。"""
        frames: list[pd.DataFrame] = []
        pending = {s: start_ms for s in symbols}
        while pending:
            by_cursor: dict[int, list[str]] = {}
            for s, c in pending.items():
                by_cursor.setdefault(c, []).append(s)
            pending = {}
            for cursor, group in by_cursor.items():
                res = self._call(self._tf.klines.batch, group, period=period,
                                 count=MAX_PAGE, start_time=cursor, end_time=end_ms,
                                 adjust="none", as_dataframe=True)
                res = res or {}
                for sym in group:
                    df = res.get(sym)
                    if df is None or df.empty:
                        continue
                    df = df.copy()
                    df["symbol"] = sym
                    frames.append(df)
                    last_ts = int(df["timestamp"].max())
                    if len(df) >= MAX_PAGE and last_ts < end_ms:
                        pending[sym] = last_ts + 1
        if not frames:
            return empty_klines()
        out = pd.concat(frames, ignore_index=True)
        out = out.drop_duplicates(subset=["symbol", "timestamp"]).sort_values(
            ["symbol", "timestamp"])
        for col in KLINE_COLUMNS:
            if col not in out.columns:
                out[col] = pd.NA
        return out[KLINE_COLUMNS].reset_index(drop=True)
```

批量方法的行为以实测为准：Step 3.5 先跑一次真实 `klines.batch` 探测（2 只标的、1d、count=5），确认返回结构（dict[symbol, DataFrame]）、count 是否按标的计、满页判定方式，记进 `docs/sdk-notes.md`；若实际形态不同（如返回单个合并 DataFrame），相应调整本方法与测试。

FakeKlines 需加 `batch(symbols, period, count, start_time, end_time, adjust, as_dataframe)`：内部有独立 `batch_script` 队列（每项：`dict[symbol, DataFrame]` 或 Exception），记录 `batch_calls`。

追加批量测试：

```python
def test_batch_range_continues_full_pages(fake_tf):
    df_full = make_kline_df("a.SH", 0, 5000, 60_000)     # a.SH 满页需续拉
    df_full2 = make_kline_df("a.SH", 5000 * 60_000, 10, 60_000)
    df_short = make_kline_df("b.SH", 0, 100, 60_000)     # b.SH 一页拉完
    fake_tf.klines.batch_script = [{"a.SH": df_full, "b.SH": df_short},
                                   {"a.SH": df_full2}]
    client = make_client(fake_tf)
    out = client.get_klines_batch_range(["a.SH", "b.SH"], "1m", 0, 10**13)
    assert len(out) == 5000 + 10 + 100
    assert len(fake_tf.klines.batch_calls) == 2
    # 第二轮只续拉 a.SH，且 start_time 接续
    second = fake_tf.klines.batch_calls[1]
    assert second["symbols"] == ["a.SH"]
    assert second["start_time"] == df_full["timestamp"].max() + 1


def test_batch_range_empty(fake_tf):
    fake_tf.klines.batch_script = [{}]
    client = make_client(fake_tf)
    out = client.get_klines_batch_range(["a.SH"], "1d", 0, 10**9)
    assert out.empty
```

注意：`classify_error` 已按 Task 1 实测的 SDK 异常类（`tickflow._exceptions.*`）做 isinstance 判断；字符串匹配仅作兜底。**另注意：非法 symbol 不抛异常、返回空 DataFrame**——无需特殊处理，`get_klines_range` 对空 df 的现有分支天然覆盖。

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_tickflow_client.py -v`
Expected: 6 passed

- [x] **Step 5: Commit**

```bash
git add src/datacenter/client/tickflow_client.py tests/conftest.py tests/test_tickflow_client.py
git commit -m "feat: TickFlowClient with rate limit, retry, kline pagination"
```

---

### Task 4: MetaStore（SQLite：coverage / sync_jobs / instruments）

**Files:**
- Create: `src/datacenter/store/meta.py`
- Test: `tests/test_meta.py`

- [x] **Step 1: 写失败测试**

`tests/test_meta.py`：

```python
import pytest
from datacenter.store.meta import MetaStore


@pytest.fixture
def meta(tmp_path):
    return MetaStore(tmp_path / "meta.db")


def test_coverage_none_initially(meta):
    assert meta.get_coverage("600000.SH", "1d") is None


def test_set_then_extend_coverage(meta):
    meta.extend_coverage("600000.SH", "1d", 1000, 2000)
    assert meta.get_coverage("600000.SH", "1d") == (1000, 2000)
    meta.extend_coverage("600000.SH", "1d", 500, 1500)   # 向左扩展
    assert meta.get_coverage("600000.SH", "1d") == (500, 2000)
    meta.extend_coverage("600000.SH", "1d", 2000, 3000)  # 向右扩展
    assert meta.get_coverage("600000.SH", "1d") == (500, 3000)
    meta.extend_coverage("600000.SH", "1d", 800, 900)    # 子区间不收缩
    assert meta.get_coverage("600000.SH", "1d") == (500, 3000)


def test_coverage_per_symbol_period(meta):
    meta.extend_coverage("600000.SH", "1d", 1000, 2000)
    assert meta.get_coverage("000001.SZ", "1d") is None
    assert meta.get_coverage("600000.SH", "1m") is None


def test_sync_job_status_roundtrip(meta):
    assert meta.pending_symbols(["a", "b"], "1d") == ["a", "b"]
    meta.mark_done("a", "1d")
    assert meta.pending_symbols(["a", "b"], "1d") == ["b"]
    meta.mark_done("a", "1m")  # 不影响 1d 的判定
    assert meta.pending_symbols(["a", "b"], "1d") == ["b"]


def test_instruments_upsert_and_count(meta):
    meta.upsert_symbols(["600000.SH", "000001.SZ"])
    assert meta.symbol_count() == 2
    meta.upsert_symbols(["600000.SH", "600519.SH"])  # 幂等
    assert meta.symbol_count() == 3
    assert meta.all_symbols() == ["000001.SZ", "600000.SH", "600519.SH"]
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_meta.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 实现**

`src/datacenter/store/meta.py`：

```python
import sqlite3
import time
from pathlib import Path

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS kline_coverage (
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (symbol, period)
);
CREATE TABLE IF NOT EXISTS sync_jobs (
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,
    status TEXT NOT NULL,          -- done
    updated_at REAL NOT NULL,
    PRIMARY KEY (symbol, period)
);
CREATE TABLE IF NOT EXISTS instruments (
    symbol TEXT PRIMARY KEY,
    exchange TEXT NOT NULL,
    code TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


class MetaStore:
    """SQLite 元数据：K线覆盖区间、回填进度、标的清单。WAL 模式支持多读单写。"""

    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)

    def close(self):
        self._conn.close()

    # ---- coverage ----
    def get_coverage(self, symbol: str, period: str) -> tuple[int, int] | None:
        row = self._conn.execute(
            "SELECT start_ms, end_ms FROM kline_coverage WHERE symbol=? AND period=?",
            (symbol, period)).fetchone()
        return (row[0], row[1]) if row else None

    def extend_coverage(self, symbol: str, period: str, start_ms: int, end_ms: int) -> None:
        """语义：该区间已向数据源请求并解析。与既有覆盖取并集，不收缩。"""
        cov = self.get_coverage(symbol, period)
        if cov:
            start_ms, end_ms = min(cov[0], start_ms), max(cov[1], end_ms)
        self._conn.execute(
            "INSERT INTO kline_coverage (symbol, period, start_ms, end_ms, updated_at)"
            " VALUES (?,?,?,?,?) ON CONFLICT(symbol, period) DO UPDATE SET"
            " start_ms=excluded.start_ms, end_ms=excluded.end_ms, updated_at=excluded.updated_at",
            (symbol, period, start_ms, end_ms, time.time()))
        self._conn.commit()

    # ---- sync jobs ----
    def mark_done(self, symbol: str, period: str) -> None:
        self._conn.execute(
            "INSERT INTO sync_jobs (symbol, period, status, updated_at) VALUES (?,?, 'done', ?)"
            " ON CONFLICT(symbol, period) DO UPDATE SET status='done', updated_at=excluded.updated_at",
            (symbol, period, time.time()))
        self._conn.commit()

    def pending_symbols(self, symbols: list[str], period: str) -> list[str]:
        if not symbols:
            return []
        marks = ",".join("?" * len(symbols))
        done = {r[0] for r in self._conn.execute(
            f"SELECT symbol FROM sync_jobs WHERE period=? AND status='done' AND symbol IN ({marks})",
            (period, *symbols))}
        return [s for s in symbols if s not in done]

    # ---- instruments ----
    def upsert_symbols(self, symbols: list[str]) -> None:
        now = time.time()
        self._conn.executemany(
            "INSERT INTO instruments (symbol, exchange, code, updated_at) VALUES (?,?,?,?)"
            " ON CONFLICT(symbol) DO UPDATE SET updated_at=excluded.updated_at",
            [(s, s.split(".")[-1], s.split(".")[0], now) for s in symbols])
        self._conn.commit()

    def symbol_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]

    def all_symbols(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT symbol FROM instruments ORDER BY symbol")]
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_meta.py -v`
Expected: 5 passed

- [x] **Step 5: Commit**

```bash
git add src/datacenter/store/meta.py tests/test_meta.py
git commit -m "feat: MetaStore with coverage, sync jobs, instruments"
```

---

### Task 5: KlineStore 写入（Parquet 分区 + 原子 rename）

**Files:**
- Create: `src/datacenter/store/klines.py`
- Test: `tests/test_kline_store.py`

- [x] **Step 1: 写失败测试**

`tests/test_kline_store.py`：

```python
import pandas as pd
import pytest

from datacenter.store.klines import KlineStore
from tests.conftest import make_kline_df

# 2025-08-01 09:30:00 Asia/Shanghai = 1754011800000 ms
T0 = 1754011800000
MIN = 60_000
DAY = 86_400_000


@pytest.fixture
def store(tmp_path):
    return KlineStore(tmp_path / "klines")


def test_write_creates_minute_partition_with_month(store):
    df = make_kline_df("600000.SH", T0, 10, MIN)
    written = store.write(df, "1m", tag="test")
    assert len(written) == 1
    path = written[0]
    assert "period=1m" in str(path) and "year=2025" in str(path) and "month=08" in str(path)
    assert path.name.startswith("part-") and path.name.endswith("-test.parquet")
    assert path.exists()


def test_write_daily_partition_without_month(store):
    df = make_kline_df("600000.SH", T0, 5, DAY)
    written = store.write(df, "1d", tag="test")
    assert "month=" not in str(written[0])


def test_write_splits_across_months(store):
    # 跨 8/9 月的数据拆成两个分区文件（2025-08-01 起每5天一根，10 根跨 46 天）
    df = make_kline_df("600000.SH", T0, 10, 5 * DAY)
    written = store.write(df, "1m", tag="test")
    assert len(written) == 2


def test_write_empty_is_noop(store):
    assert store.write(pd.DataFrame(), "1d", tag="test") == []


def test_no_tmp_files_left(store, tmp_path):
    df = make_kline_df("600000.SH", T0, 10, MIN)
    store.write(df, "1m", tag="test")
    tmps = list((tmp_path / "klines").rglob(".tmp-*"))
    assert tmps == []
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_kline_store.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 实现（写入部分）**

`src/datacenter/store/klines.py`：

```python
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from datacenter.constants import MINUTE_PERIODS


class KlineStore:
    """K线 Parquet 存储。写入：按分区拆帧 → 写临时文件 → 原子 rename。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def write(self, df: pd.DataFrame, period: str, tag: str) -> list[Path]:
        if df is None or df.empty:
            return []
        df = df.copy()
        ts = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")
        df["year"] = ts.dt.strftime("%Y")
        partition_cols = ["year"]
        if period in MINUTE_PERIODS:
            df["month"] = ts.dt.strftime("%m")
            partition_cols.append("month")

        written = []
        for keys, part in df.groupby(partition_cols, observed=True):
            keys = keys if isinstance(keys, tuple) else (keys,)
            dirpath = self.root / f"period={period}" / f"year={keys[0]}"
            if len(keys) > 1:
                dirpath = dirpath / f"month={keys[1]}"
            dirpath.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            tmp = dirpath / f".tmp-{stamp}-{tag}.parquet"
            final = dirpath / f"part-{stamp}-{tag}.parquet"
            part.drop(columns=partition_cols).to_parquet(tmp, index=False, compression="zstd")
            os.replace(tmp, final)  # 同目录原子 rename
            written.append(final)
        return written
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_kline_store.py -v`
Expected: 5 passed

- [x] **Step 5: Commit**

```bash
git add src/datacenter/store/klines.py tests/test_kline_store.py
git commit -m "feat: KlineStore partitioned parquet writes with atomic rename"
```

---

### Task 6: KlineStore 读取（DuckDB + 分区裁剪 + 去重）

**Files:**
- Modify: `src/datacenter/store/klines.py`
- Modify: `tests/test_kline_store.py`

读取语义：同一 `(symbol, timestamp)` 可能被重复写入（回填重跑、日终覆盖），**后写胜出**——靠文件名时间戳 `ORDER BY filename DESC` 实现。

- [x] **Step 1: 追加失败测试**

`tests/test_kline_store.py` 追加：

```python
def test_read_empty_store_returns_empty(store):
    out = store.read(["600000.SH"], "1d", 0, 10**13)
    assert out.empty
    assert "symbol" in out.columns and "timestamp" in out.columns


def test_read_roundtrip(store):
    df = make_kline_df("600000.SH", T0, 10, DAY)
    store.write(df, "1d", tag="a")
    out = store.read(["600000.SH"], "1d", T0, T0 + 10 * DAY)
    assert len(out) == 10
    assert list(out["timestamp"]) == sorted(df["timestamp"])


def test_read_filters_by_range_and_symbols(store):
    store.write(make_kline_df("600000.SH", T0, 10, DAY), "1d", tag="a")
    store.write(make_kline_df("000001.SZ", T0, 10, DAY), "1d", tag="a")
    out = store.read(["600000.SH"], "1d", T0 + 2 * DAY, T0 + 5 * DAY)
    assert len(out) == 4
    assert set(out["symbol"]) == {"600000.SH"}


def test_read_dedup_last_write_wins(store):
    df1 = make_kline_df("600000.SH", T0, 5, DAY)           # close = base+0.5
    store.write(df1, "1d", tag="old")
    df2 = df1.copy()
    df2["close"] = 999.0                                    # 修正数据后写
    store.write(df2, "1d", tag="fix")
    out = store.read(["600000.SH"], "1d", T0, T0 + 5 * DAY)
    assert len(out) == 5
    assert (out["close"] == 999.0).all()


def test_read_is_readonly_and_repeatable(store):
    store.write(make_kline_df("600000.SH", T0, 5, DAY), "1d", tag="a")
    out1 = store.read(["600000.SH"], "1d", 0, 10**13)
    out2 = store.read(["600000.SH"], "1d", 0, 10**13)
    pd.testing.assert_frame_equal(out1, out2)
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_kline_store.py -v`
Expected: 新测试 FAIL（`AttributeError: 'KlineStore' object has no attribute 'read'`）

- [x] **Step 3: 实现（读取部分，追加到 klines.py）**

```python
import duckdb

from datacenter.client.tickflow_client import KLINE_COLUMNS, empty_klines
from datacenter.constants import ALL_PERIODS


class KlineStore:
    # ... write 保持不变 ...

    def read(self, symbols: list[str], period: str,
             start_ms: int, end_ms: int) -> pd.DataFrame:
        if period not in ALL_PERIODS:
            raise ValueError(f"unknown period: {period}")
        if not symbols:
            return empty_klines()
        glob = str(self.root / f"period={period}" / "**" / "*.parquet")
        sql = """
            SELECT symbol, timestamp, open, high, low, close, volume, amount
            FROM read_parquet(?, hive_partitioning=true, filename=true, union_by_name=true)
            WHERE symbol = ANY(?::VARCHAR[]) AND timestamp BETWEEN ? AND ?
            QUALIFY row_number() OVER (
                PARTITION BY symbol, timestamp ORDER BY filename DESC
            ) = 1
            ORDER BY symbol, timestamp
        """
        try:
            out = duckdb.sql(sql, params=[glob, list(symbols), start_ms, end_ms]).df()
        except duckdb.IOException:
            return empty_klines()  # 尚无该周期数据
        return out[KLINE_COLUMNS]
```

注意：若 DuckDB 对空 glob 抛的不是 `IOException`（版本差异），运行测试看真实异常类并调整捕获范围（兜底 `duckdb.Error`）。

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_kline_store.py -v`
Expected: 10 passed（含 Task 5 的 5 个）

- [x] **Step 5: Commit**

```bash
git add src/datacenter/store/klines.py tests/test_kline_store.py
git commit -m "feat: KlineStore duckdb reads with partition pruning and last-wins dedup"
```

---

### Task 7: CacheResolver（区间减法 + 回源落库）

**Files:**
- Create: `src/datacenter/resolver.py`
- Test: `tests/test_resolver.py`

- [x] **Step 1: 写失败测试**

`tests/test_resolver.py`：

```python
import pytest

from datacenter.resolver import CacheResolver, missing_segments
from tests.conftest import FakeTickFlow, make_kline_df

T0, DAY = 1754011800000, 86_400_000


def test_missing_segments_no_coverage():
    assert missing_segments(100, 200, None) == [(100, 200)]


def test_missing_segments_full_hit():
    assert missing_segments(120, 180, (100, 200)) == []


def test_missing_segments_left_and_right():
    assert missing_segments(50, 300, (100, 200)) == [(50, 99), (201, 300)]


@pytest.fixture
def env(tmp_path, fake_tf):
    from datacenter.store.meta import MetaStore
    from datacenter.store.klines import KlineStore
    from datacenter.client.tickflow_client import TickFlowClient
    meta = MetaStore(tmp_path / "meta.db")
    store = KlineStore(tmp_path / "klines")
    client = TickFlowClient(tf=fake_tf, rate_per_sec=1000, sleep=lambda s: None)
    return CacheResolver(meta=meta, klines=store, client=client), fake_tf, meta


def test_full_miss_fetches_and_caches(env):
    resolver, fake_tf, meta = env
    fake_tf.klines.queue(make_kline_df("600000.SH", T0, 5, DAY))
    resolver.ensure("600000.SH", "1d", T0, T0 + 5 * DAY)
    assert meta.get_coverage("600000.SH", "1d") == (T0, T0 + 5 * DAY)
    assert len(fake_tf.klines.calls) == 1
    # 二次查询不回源
    resolver.ensure("600000.SH", "1d", T0, T0 + 5 * DAY)
    assert len(fake_tf.klines.calls) == 1


def test_empty_remote_result_still_marks_coverage(env):
    """未上市/停牌区间回源为空，也必须标记覆盖，防止反复打空。"""
    resolver, fake_tf, meta = env
    import pandas as pd
    fake_tf.klines.queue(pd.DataFrame())
    resolver.ensure("600000.SH", "1d", T0, T0 + 5 * DAY)
    assert meta.get_coverage("600000.SH", "1d") == (T0, T0 + 5 * DAY)
    resolver.ensure("600000.SH", "1d", T0, T0 + 5 * DAY)
    assert len(fake_tf.klines.calls) == 1


def test_partial_miss_only_fetches_gaps(env):
    resolver, fake_tf, meta = env
    fake_tf.klines.queue(make_kline_df("600000.SH", T0, 5, DAY))
    resolver.ensure("600000.SH", "1d", T0, T0 + 5 * DAY)
    # 扩展请求右侧 3 天：只回源缺口段
    fake_tf.klines.queue(make_kline_df("600000.SH", T0 + 5 * DAY + 1, 3, DAY))
    resolver.ensure("600000.SH", "1d", T0, T0 + 8 * DAY)
    last = fake_tf.klines.calls[-1]
    assert last["start_time"] == T0 + 5 * DAY + 1
    assert meta.get_coverage("600000.SH", "1d") == (T0, T0 + 8 * DAY)
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_resolver.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 实现**

`src/datacenter/resolver.py`：

```python
from datacenter.client.tickflow_client import TickFlowClient
from datacenter.store.klines import KlineStore
from datacenter.store.meta import MetaStore


def missing_segments(req_start: int, req_end: int,
                     coverage: tuple[int, int] | None) -> list[tuple[int, int]]:
    """请求区间减去覆盖区间，返回缺口（毫秒闭区间）。区内小洞不管（第一期）。"""
    if req_start > req_end:
        return []
    if coverage is None:
        return [(req_start, req_end)]
    cstart, cend = coverage
    segs = []
    if req_start < cstart:
        segs.append((req_start, min(req_end, cstart - 1)))
    if req_end > cend:
        segs.append((max(req_start, cend + 1), req_end))
    return segs


class CacheResolver:
    """缓存逻辑唯一决策者：命中放行，缺口回源落库并扩展覆盖区间。"""

    def __init__(self, meta: MetaStore, klines: KlineStore, client: TickFlowClient):
        self._meta = meta
        self._klines = klines
        self._client = client

    def ensure(self, symbol: str, period: str, start_ms: int, end_ms: int) -> None:
        coverage = self._meta.get_coverage(symbol, period)
        for seg_start, seg_end in missing_segments(start_ms, end_ms, coverage):
            df = self._client.get_klines_range(symbol, period, seg_start, seg_end)
            self._klines.write(df, period, tag="resolver")
            # 无论回源是否有数据，该段都标记已解析（防打空）
            self._meta.extend_coverage(symbol, period, seg_start, seg_end)
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_resolver.py -v`
Expected: 6 passed

- [x] **Step 5: Commit**

```bash
git add src/datacenter/resolver.py tests/test_resolver.py
git commit -m "feat: CacheResolver with interval subtraction and fetch-through"
```

---

### Task 8: DataCenter 门面（端到端）

**Files:**
- Create: `src/datacenter/api.py`
- Modify: `src/datacenter/__init__.py`
- Test: `tests/test_api.py`

- [x] **Step 1: 写失败测试**

`tests/test_api.py`：

```python
import pytest

from datacenter import DataCenter
from tests.conftest import FakeTickFlow, make_kline_df

T0, DAY = 1754011800000, 86_400_000


@pytest.fixture
def dc(tmp_path):
    fake = FakeTickFlow(symbols=["600000.SH", "000001.SZ"])
    fake.klines.queue(make_kline_df("600000.SH", T0, 10, DAY))
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake, rate_per_sec=1000)
    return dc, fake


def test_get_klines_end_to_end(dc):
    dc_, fake = dc
    df = dc_.get_klines("600000.SH", "1d", T0, T0 + 10 * DAY)
    assert len(df) == 10
    assert df["timestamp"].is_monotonic_increasing
    # 第二次完全走缓存
    df2 = dc_.get_klines("600000.SH", "1d", T0, T0 + 10 * DAY)
    assert len(df2) == 10
    assert len(fake.klines.calls) == 1


def test_get_klines_validates_period(dc):
    dc_, _ = dc
    with pytest.raises(ValueError):
        dc_.get_klines("600000.SH", "2d", T0, T0 + DAY)


def test_list_symbols_populates_instruments(dc):
    dc_, fake = dc
    symbols = dc_.list_symbols()
    assert symbols == ["000001.SZ", "600000.SH"]
    assert dc_.list_symbols() == ["000001.SZ", "600000.SH"]  # 走本地
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL（ImportError）

- [x] **Step 3: 实现**

`src/datacenter/api.py`：

```python
from pathlib import Path

import pandas as pd

from datacenter.client.tickflow_client import TickFlowClient
from datacenter.constants import ALL_PERIODS
from datacenter.resolver import CacheResolver
from datacenter.store.klines import KlineStore
from datacenter.store.meta import MetaStore

THREE_YEARS_MS = 3 * 365 * 86_400_000


class DataCenter:
    """门面：回测引擎的唯一入口。本地优先，缺失回源，查到即存。"""

    def __init__(self, data_dir: str | Path = "data", client_tf=None,
                 rate_per_sec: float = 10.0):
        data_dir = Path(data_dir)
        self.meta = MetaStore(data_dir / "meta.db")
        self.klines = KlineStore(data_dir / "klines")
        self.client = TickFlowClient(tf=client_tf, rate_per_sec=rate_per_sec)
        self.resolver = CacheResolver(self.meta, self.klines, self.client)

    def get_klines(self, symbol: str, period: str = "1d",
                   start_ms: int | None = None, end_ms: int | None = None) -> pd.DataFrame:
        if period not in ALL_PERIODS:
            raise ValueError(f"unknown period {period!r}, expected one of {ALL_PERIODS}")
        import time
        end_ms = end_ms if end_ms is not None else int(time.time() * 1000)
        start_ms = start_ms if start_ms is not None else end_ms - THREE_YEARS_MS
        self.resolver.ensure(symbol, period, start_ms, end_ms)
        return self.klines.read([symbol], period, start_ms, end_ms)

    def list_symbols(self, universe: str = "CN_Equity_A") -> list[str]:
        if self.meta.symbol_count() == 0:
            self.meta.upsert_symbols(self.client.list_universe_symbols(universe))
        return self.meta.all_symbols()
```

`src/datacenter/__init__.py`：

```python
from datacenter.api import DataCenter
from datacenter.exceptions import DataCenterError, DataUnavailableError, RateLimitError, TickFlowError

__all__ = ["DataCenter", "DataCenterError", "DataUnavailableError", "RateLimitError", "TickFlowError"]
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_api.py -v`
Expected: 3 passed

- [x] **Step 5: 全量回归 + Commit**

Run: `uv run pytest -v`
Expected: 全部 passed

```bash
git add src/datacenter/api.py src/datacenter/__init__.py tests/test_api.py
git commit -m "feat: DataCenter facade end-to-end"
```

---

### Task 9: BackfillJob（批量回填 + 断点续传）

**Files:**
- Create: `src/datacenter/jobs/backfill.py`
- Test: `tests/test_backfill.py`

机制：按 `BACKFILL_ORDER` 逐周期处理；每周期内取 `pending_symbols`（跳过已完成 = 断点续传）；按批（日线 200 标的/批、分钟 100 标的/批，对齐套餐限制）调 `client.get_klines_batch_range`；每批结果按分区落盘，逐 symbol 标记 coverage + done。**整批失败则整批标记 failed**（批量请求是原子调用，无法区分单只失败；重跑整批成本可接受）。批量接口下并发无意义（限流是瓶颈），回填为顺序循环。

- [x] **Step 1: 写失败测试**

`tests/test_backfill.py`：

```python
import pandas as pd
import pytest

from datacenter import DataCenter
from datacenter.jobs.backfill import backfill
from tests.conftest import FakeTickFlow, make_kline_df

T0, DAY = 1754011800000, 86_400_000


def make_dc(tmp_path, fake):
    # max_retries=0：失败测试依赖"异常立即抛出"，默认重试会消耗后续队列元素
    return DataCenter(data_dir=tmp_path / "data", client_tf=fake, rate_per_sec=10_000,
                      max_retries=0)


def test_backfill_fetches_all_pending_symbols(tmp_path):
    fake = FakeTickFlow(symbols=["a.SH", "b.SH", "c.SH"])
    fake.klines.batch_script = [
        {s: make_kline_df(s, T0, 3, DAY) for s in ["a.SH", "b.SH"]},
        {"c.SH": make_kline_df("c.SH", T0, 3, DAY)},
    ]
    dc = make_dc(tmp_path, fake)
    report = backfill(dc, periods=["1d"], start_ms=T0, end_ms=T0 + 3 * DAY,
                      batch_size=2)
    assert sorted(report["done"]) == ["a.SH", "b.SH", "c.SH"]
    assert report["failed"] == {}
    assert dc.meta.pending_symbols(["a.SH", "b.SH", "c.SH"], "1d") == []
    df = dc.get_klines("a.SH", "1d", T0, T0 + 3 * DAY)  # 缓存命中不回源
    assert len(df) == 3


def test_backfill_resume_skips_done(tmp_path):
    fake = FakeTickFlow(symbols=["a.SH", "b.SH"])
    dc = make_dc(tmp_path, fake)
    dc.list_symbols()
    dc.meta.mark_done("a.SH", "1d")  # 模拟上次已完成
    fake.klines.batch_script = [{"b.SH": make_kline_df("b.SH", T0, 3, DAY)}]
    report = backfill(dc, periods=["1d"], start_ms=T0, end_ms=T0 + 3 * DAY)
    assert report["done"] == ["b.SH"]
    assert fake.klines.batch_calls[0]["symbols"] == ["b.SH"]


def test_backfill_batch_failure_marks_whole_batch(tmp_path):
    fake = FakeTickFlow(symbols=["a.SH", "b.SH"])
    fake.klines.batch_script = [Exception("boom")]
    dc = make_dc(tmp_path, fake)
    report = backfill(dc, periods=["1d"], start_ms=T0, end_ms=T0 + 3 * DAY)
    assert report["done"] == []
    assert set(report["failed"]) == {"a.SH", "b.SH"}
    assert dc.meta.pending_symbols(["a.SH", "b.SH"], "1d") == ["a.SH", "b.SH"]


def test_backfill_empty_batch_result_still_marks_done(tmp_path):
    """批量返回空（如全部未上市期间）也必须标记 done + coverage，防止反复打空。"""
    fake = FakeTickFlow(symbols=["a.SH"])
    fake.klines.batch_script = [{}]
    dc = make_dc(tmp_path, fake)
    report = backfill(dc, periods=["1d"], start_ms=T0, end_ms=T0 + 3 * DAY)
    assert report["done"] == ["a.SH"]
    assert dc.meta.get_coverage("a.SH", "1d") == (T0, T0 + 3 * DAY)
```

给 `DataCenter` 加透传参数 `max_retries: int = 3` 传到 TickFlowClient（api.py 小改，属于本任务范围）。

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_backfill.py -v`
Expected: FAIL（ModuleNotFoundError / TypeError）

- [x] **Step 3: 实现**

`src/datacenter/api.py` 的 `__init__` 签名改为 `(self, data_dir="data", client_tf=None, rate_per_sec=10.0, max_retries=3)`，并传给 `TickFlowClient`。

`src/datacenter/jobs/backfill.py`：

```python
import logging
import time

from datacenter.api import DataCenter
from datacenter.constants import (BACKFILL_ORDER, DAILY_HISTORY_DAYS,
                                  MINUTE_HISTORY_DAYS, MINUTE_PERIODS)

log = logging.getLogger(__name__)


def backfill(dc: DataCenter, periods: list[str] | None = None,
             start_ms: int | None = None, end_ms: int | None = None,
             batch_size: int | None = None) -> dict:
    """全市场历史回填。断点续传：已标记 done 的 (symbol, period) 跳过。

    分钟周期默认只拉最近 365 天（套餐硬限制），日线级默认 3 年。
    batch_size 默认按周期取套餐上限（分钟 100 / 日线 200）。
    """
    end_ms = end_ms if end_ms is not None else int(time.time() * 1000)
    symbols = dc.list_symbols()
    report = {"done": [], "failed": {}}

    for period in (periods or BACKFILL_ORDER):
        default_days = MINUTE_HISTORY_DAYS if period in MINUTE_PERIODS else DAILY_HISTORY_DAYS
        p_start = start_ms if start_ms is not None else end_ms - default_days * 86_400_000
        size = batch_size or (100 if period in MINUTE_PERIODS else 200)
        todo = dc.meta.pending_symbols(symbols, period)
        log.info("period=%s pending=%d", period, len(todo))
        for i in range(0, len(todo), size):
            batch = todo[i:i + size]
            try:
                df = dc.client.get_klines_batch_range(batch, period, p_start, end_ms)
            except Exception as exc:
                for s in batch:
                    report["failed"][s] = str(exc)
                log.warning("batch failed: period=%s [%d:%d]: %s", period, i, i + size, exc)
                continue
            dc.klines.write(df, period, tag="backfill")
            for s in batch:
                # 空数据同样是"已解析"，标记覆盖防打空
                dc.meta.extend_coverage(s, period, p_start, end_ms)
                dc.meta.mark_done(s, period)
                report["done"].append(s)
            log.info("period=%s batch %d-%d done", period, i, i + len(batch))
    return report
```

注意：resolver 与 backfill 共用 client（令牌桶在 client 内，全局限速生效）；写入在回填主线程单点进行，满足单写者纪律。**回填前把 client 速率调到对应套餐档位**（分钟批量 30 次/分 = 0.5/s；日线批量 60 次/分 = 1/s），由 CLI 的 `--rate` 传入。

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_backfill.py -v`
Expected: 4 passed

- [x] **Step 5: 全量回归 + Commit**

Run: `uv run pytest -v`
Expected: 全部 passed

```bash
git add src/datacenter/jobs/backfill.py src/datacenter/api.py tests/test_backfill.py
git commit -m "feat: resumable batch backfill job"
```

---

### Task 10: 回填 CLI + README + 真实回源 smoke

**Files:**
- Create: `scripts/backfill.py`
- Create: `README.md`

- [x] **Step 1: 写回填 CLI**

`scripts/backfill.py`：

```python
"""历史回填入口。
用法:
  uv run python scripts/backfill.py                      # 全量：11周期 × 全市场 × 3年
  uv run python scripts/backfill.py --periods 1d,1w      # 只补指定周期
  uv run python scripts/backfill.py --rate 20 --workers 16
中断后重跑同一命令即可续传。
"""
import argparse
import logging
import time

from datacenter import DataCenter
from datacenter.jobs.backfill import backfill

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--periods", type=str, default=None, help="逗号分隔，默认全部（先粗后细）")
    p.add_argument("--rate", type=float, default=1.0,
                   help="每秒请求上限（日线批量 60次/分=1.0，分钟批量 30次/分=0.5）")
    p.add_argument("--batch-size", type=int, default=None,
                   help="默认按周期取套餐上限（日线 200 / 分钟 100）")
    p.add_argument("--data-dir", type=str, default="data")
    args = p.parse_args()

    dc = DataCenter(data_dir=args.data_dir, rate_per_sec=args.rate)
    periods = args.periods.split(",") if args.periods else None
    t0 = time.time()
    report = backfill(dc, periods=periods, batch_size=args.batch_size)
    print(f"\n耗时 {time.time() - t0:.0f}s | 完成 {len(report['done'])} 个 symbol×period"
          f" | 失败 {len(report['failed'])} 个")
    if report["failed"]:
        print("失败样例:", list(report["failed"].items())[:10])


if __name__ == "__main__":
    main()
```

- [x] **Step 2: 真实回源 smoke（小规模）**

```bash
uv run python scripts/backfill.py --periods 1d --rate 1.0
```

预期：批量拉全市场 3 年日线（5555 只 × 28 批 ≈ 28 次请求，1 分钟内完成），`data/klines/period=1d/` 出现按年分区文件，`data/meta.db` 存在。

随后验证读取（REPL 或临时脚本）：

```python
from datacenter import DataCenter
dc = DataCenter()
df = dc.get_klines("600000.SH", "1d")   # 应秒回（走缓存，无网络请求）
print(len(df), df["timestamp"].min(), df["timestamp"].max())
```

预期：约 730±10 行（3 年交易日），时间跨度覆盖近 3 年。**注意：此行数与数据质量是真实校验，若明显偏少需排查分页逻辑。**

- [x] **Step 3: 写 README**

`README.md`：项目简介、安装（`uv sync` + `TICKFLOW_API_KEY`）、快速上手（`DataCenter.get_klines` 示例）、回填命令、目录结构、设计文档与 spec 的链接、分期说明（二三期待做）。

- [ ] **Step 4: Commit**

```bash
git add scripts/backfill.py README.md
git commit -m "feat: backfill CLI + README; verified with live daily-bar smoke"
```

- [ ] **Step 5: （可选）启动全量回填**

```bash
uv run python scripts/backfill.py --rate 0.5   # 分钟批量档；日线部分会偏慢但安全
```

预计：日线级 5 个周期几分钟；分钟级 5 个周期 × 365 天约 30~60 分钟（批量 30 次/分 × 100 标的，1m 线每标的 365 天约 8.8 万条需 ~18 页，时间窗续拉自动处理）。中断后重跑即续传。

---

## 完成标准（第一期 DoD）

1. `uv run pytest` 全绿
2. `dc.get_klines` 第二次调用零网络请求（缓存命中）
3. 真实 smoke：全市场日线回填完成且可读取
4. 回填中断重跑不重复拉取（断点续传）
5. git 历史含每个任务的独立 commit

## 明确不做（留给二三期）

- 复权计算、除权因子表、财务/元数据接口缓存、标的池缓存 → 第二期
- 数据校验（连续性/抽样比对/交叉校验）、日终维护任务 → 第二期
- WebSocket 实时采集、盘中半可变层 → 第三期
