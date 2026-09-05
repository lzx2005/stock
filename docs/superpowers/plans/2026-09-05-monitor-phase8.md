# 第八期 · 日内盯盘系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 常驻盯盘守护进程：注册在 monitor.db 里的 Python 脚本（`check(ctx)`）在交易时段按各自间隔轮询执行，条件边沿触发时亮/灭「买入灯/卖出灯」并推送 Bark，webui 加「盯盘」tab 管理，配套「盯盘专家」skill 把自然语言转成脚本。

**Architecture:** 独立守护进程（`src/monitor/`）+ SQLite `data/monitor.db`（tasks/signals 两表，脚本代码存库内）为唯一接口；webui（现有 FastAPI+React）读写同一 DB 做管理界面；Bark 推送写死 `notify.py`，key 在 `data/monitor_config.json`。

**Tech Stack:** Python ≥3.11（stdlib sqlite3/urllib，不加新依赖）、FastAPI、React+antd5（现有栈）、pytest。

**Spec:** `docs/superpowers/specs/2026-09-05-intraday-monitor-design.md`

## Global Constraints

- **用户不用 git**：不 commit、不 push。本计划**不含 Commit 步骤**（与历期一致，Commit 步永不执行）。
- 测试命令：`.venv/bin/python -m pytest tests/`（`--timeout=60`）；单文件 `-v`。
- 真实数据命令前先 `source ~/.zshrc`（TICKFLOW_API_KEY）。**单元测试一律不打真实接口**（fake DataCenter / mock HTTP）。
- `data/` 已 gitignore；`monitor.db`、`monitor_config.json` 都在 data/ 下。
- 不加第三方依赖（Bark 用 urllib；调度用 time.sleep 循环）。
- 交易时段（北京）：9:25~11:30、13:00~15:00；最小调度粒度 60s。
- 完成每个 Task 后把对应 `- [ ]` 改 `- [x]`；全部完成后更新 HELP.md。

---

### Task 1: `src/monitor/store.py` — monitor.db 存储层

**Files:**
- Create: `src/monitor/__init__.py`（空文件）
- Create: `src/monitor/store.py`
- Test: `tests/test_monitor_store.py`

**Interfaces:**
- Produces（后续 Task 全部依赖这些签名）:

```python
class MonitorStore:
    def __init__(self, db_path: str | Path): ...        # 建表（幂等），WAL
    def add_task(self, name: str, symbol: str, script: str,
                 interval_sec: int = 60, notify: int = 1) -> int        # → task_id
    def list_tasks(self) -> list[dict]: ...             # 全字段 dict，按 id 排序
    def get_task(self, task_id: int) -> dict | None: ...
    def update_task(self, task_id: int, *, name=None, symbol=None,
                    script=None, interval_sec=None, notify=None) -> None  # 只改非 None 字段
    def set_enabled(self, task_id: int, enabled: int) -> None
    def delete_task(self, task_id: int) -> None
    def bump_poll(self, task_id: int, ts_ms: int) -> None   # poll_count+1, last_run_at=ts_ms
    def record_error(self, task_id: int, message: str) -> None  # error_count+1, last_error
    def set_lamp(self, task_id: int, field: str, value: int) -> None  # field ∈ {"buy_on","sell_on"}
    def add_signal(self, task_id: int, ts_ms: int, kind: str,
                   price: float | None, message: str) -> int
    def list_signals(self, task_id: int | None = None, limit: int = 200) -> list[dict]  # 按 ts 倒序
```

表结构按 spec §5（tasks: id/name/symbol/script/interval_sec/enabled/notify/buy_on/sell_on/poll_count/signal_count/last_run_at/error_count/last_error/created_at；signals: id/task_id/ts/kind/price/message）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_monitor_store.py
from monitor.store import MonitorStore


def test_task_crud_and_toggle(tmp_path):
    st = MonitorStore(tmp_path / "m.db")
    tid = st.add_task("600869 低位区", "600869.SH", "def check(ctx): ...",
                      interval_sec=60, notify=1)
    t = st.get_task(tid)
    assert t["symbol"] == "600869.SH" and t["enabled"] == 1 and t["buy_on"] == 0
    st.update_task(tid, interval_sec=120, script="def check(ctx): return {}")
    assert st.get_task(tid)["interval_sec"] == 120
    st.set_enabled(tid, 0)
    assert st.get_task(tid)["enabled"] == 0
    assert len(st.list_tasks()) == 1
    st.delete_task(tid)
    assert st.list_tasks() == []


def test_lamp_poll_error_signal(tmp_path):
    st = MonitorStore(tmp_path / "m.db")
    tid = st.add_task("t", "600869.SH", "def check(ctx): ...")
    st.set_lamp(tid, "buy_on", 1)
    st.bump_poll(tid, 1000)
    st.record_error(tid, "boom")
    st.add_signal(tid, 1000, "buy_on", 12.34, "进入低位区")
    t = st.get_task(tid)
    assert (t["buy_on"], t["poll_count"], t["error_count"]) == (1, 1, 1)
    assert t["last_error"] == "boom" and t["last_run_at"] == 1000
    sigs = st.list_signals(tid)
    assert sigs[0]["kind"] == "buy_on" and sigs[0]["price"] == 12.34


def test_schema_idempotent(tmp_path):
    MonitorStore(tmp_path / "m.db")
    MonitorStore(tmp_path / "m.db")  # 第二次初始化不报错
```

- [ ] **Step 2: 跑测试确认失败** — `.venv/bin/python -m pytest tests/test_monitor_store.py -v`，预期 ModuleNotFoundError。
- [ ] **Step 3: 实现** `src/monitor/store.py`：sqlite3 连接（`check_same_thread=False`，`PRAGMA journal_mode=WAL`，`row_factory=sqlite3.Row`），`CREATE TABLE IF NOT EXISTS` 两表（spec §5 全字段），方法按上面签名逐条 SQL。`set_lamp` 校验 field 白名单。
- [ ] **Step 4: 跑测试确认通过**。

---

### Task 2: `src/monitor/notify.py` — Bark 推送

**Files:**
- Create: `src/monitor/notify.py`
- Test: `tests/test_monitor_notify.py`

**Interfaces:**
- Consumes: 无
- Produces:

```python
def load_config(path: str | Path = "data/monitor_config.json") -> dict
    # 文件不存在/坏 JSON → {}；{"bark_key": ..., "bark_server": 可选}

def send(text: str, config: dict | None = None,
         config_path: str | Path = "data/monitor_config.json") -> bool
    # config=None 时 load_config(config_path)。无 key → 返回 False（不抛）。
    # POST {server}/push JSON {"device_key","title":"盯盘信号","body":text,
    #   "group":"盯盘","sound":"bell","level":"timeSensitive"}，10s 超时。
    # 网络/HTTP 异常 → 返回 False（不抛）。code==200 → True。
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_monitor_notify.py
import json
import urllib.request
from unittest.mock import patch, MagicMock
from monitor import notify


def test_load_config_missing(tmp_path):
    assert notify.load_config(tmp_path / "none.json") == {}


def test_send_no_key(tmp_path):
    assert notify.send("hi", config={}) is False


def test_send_success_payload(tmp_path):
    resp = MagicMock(); resp.read.return_value = b'{"code":200}'
    resp.__enter__ = lambda s: s; resp.__exit__ = lambda *a: None
    with patch.object(urllib.request, "urlopen", return_value=resp) as m:
        ok = notify.send("买入灯亮", config={"bark_key": "K1"})
    assert ok is True
    req = m.call_args[0][0]
    assert req.full_url == "https://api.day.app/push"
    body = json.loads(req.data)
    assert body["device_key"] == "K1" and body["body"] == "买入灯亮"
    assert body["group"] == "盯盘" and body["level"] == "timeSensitive"


def test_send_network_error_swallowed():
    with patch.object(urllib.request, "urlopen", side_effect=OSError("down")):
        assert notify.send("x", config={"bark_key": "K1"}) is False
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现**（stdlib urllib，逻辑同 `scripts/test_bark.py` 的 push()，加配置加载与异常吞咽）。
- [ ] **Step 4: 跑测试确认通过**。

---

### Task 3: `src/monitor/runtime.py` — 脚本契约 MonitorContext

**Files:**
- Create: `src/monitor/runtime.py`
- Test: `tests/test_monitor_runtime.py`

**Interfaces:**
- Consumes: `DataCenter.get_klines(symbol, period, start_ms, end_ms, adjust)`；`FactorStore.get(symbol, name, params, period, s_ms, e_ms)`→Series；Task 1 无依赖。
- Produces:

```python
class MonitorContext:
    def __init__(self, dc, fs, symbol: str): ...
    def price(self) -> float                 # minute_bars() 最后一根 close；空 → 抛 DataError
    def minute_bars(self) -> DataFrame       # dc.get_klines(symbol,"1m",今日0点,now)；空 df 原样返回
    def daily(self, n: int) -> DataFrame     # dc.get_klines(symbol,"1d",n 天前,now)（含今日合成日K）
    def factor(self, name: str, params: dict, n: int) -> Series  # fs.get(...,"1d",窗口)

def load_check(script: str) -> Callable      # exec；无 check/不可调用 → ValueError
def run_check(script: str, ctx) -> dict      # 校验返回：dict 且 buy/sell ∈ {True,False,None}，
                                             # 缺省补 None，msg 转 str；非法 → ValueError
```

实现要点：模块顶部 `import factors.factors  # noqa: F401`（显式注册）；`daily(n)` 的 start 取 `today - (n*2) 天` 后 `tail(n)`（自然日 vs 交易日冗余）；自定义 `class DataError(Exception)` 表示无当日数据。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_monitor_runtime.py
import pandas as pd
import pytest
from monitor.runtime import MonitorContext, load_check, run_check, DataError


class FakeDC:
    def __init__(self):
        day = pd.DataFrame({"timestamp": [1000, 2000], "open": [1, 2],
                            "high": [1, 2], "low": [1, 2], "close": [10.0, 11.0],
                            "volume": [100, 200], "amount": [1000.0, 2200.0]})
        self.min = day.copy(); self.day = day
    def get_klines(self, symbol, period, s, e, adjust="forward"):
        return self.min if period == "1m" else self.day


class FakeFS:
    def get(self, symbol, name, params, period, s, e):
        return pd.Series([1.0, 2.0], index=[1000, 2000])


def ctx():
    return MonitorContext(FakeDC(), FakeFS(), "600869.SH")


def test_ctx_methods():
    c = ctx()
    assert c.price() == 11.0
    assert len(c.minute_bars()) == 2 and len(c.daily(5)) == 2
    assert c.factor("ma", {"n": 20}, 60).iloc[-1] == 2.0


def test_price_empty_raises():
    c = ctx(); c.dc.min = c.dc.min.iloc[0:0]
    with pytest.raises(DataError):
        c.price()


def test_load_and_run_check():
    script = 'def check(ctx):\n    return {"buy": True, "msg": "hi"}\n'
    fn = load_check(script)
    assert callable(fn)
    out = run_check(script, ctx())
    assert out == {"buy": True, "sell": None, "msg": "hi"}


def test_load_check_missing():
    with pytest.raises(ValueError):
        load_check("x = 1")


def test_run_check_bad_return():
    with pytest.raises(ValueError):
        run_check('def check(ctx):\n    return {"buy": "yes"}\n', ctx())
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现**（注意 fake 的 `dc.get_klines` 签名为关键字兼容即可；真实 DataCenter 用 `adjust="forward"`）。
- [ ] **Step 4: 跑测试确认通过**。

---

### Task 4: `src/monitor/daemon.py` — 调度与边沿判定

**Files:**
- Create: `src/monitor/daemon.py`
- Test: `tests/test_monitor_daemon.py`

**Interfaces:**
- Consumes: `MonitorStore`（Task 1）、`runtime.load_check/run_check/MonitorContext/DataError`（Task 3）、`notify.send`（Task 2，以函数注入便于 mock）。
- Produces:

```python
def edge_transition(field: str, old: int, new) -> str | None
    # field ∈ {"buy","sell"}（不带 _on 后缀）。new is None → None；
    # new=True 且 old=0 → f"{field}_on"；new=False 且 old=1 → f"{field}_off"；否则 None。

def in_trading_hours(ts_ms: int) -> bool   # 北京时间 9:25~11:30 或 13:00~15:00

class MonitorDaemon:
    def __init__(self, store: MonitorStore, dc, fs, send_fn=notify.send,
                 interval_default: int = 60): ...
    def tick(self, now_ms: int | None = None) -> None
        # 非交易时段 → 直接返回。重读 tasks；对每个 enabled 且到期的任务：
        # 构造 ctx → run_check（DataError/取数空 → 静默跳过，不记错误；
        # 其他异常 → record_error）→ bump_poll → buy/sell 各 edge_transition：
        # 有边沿 → set_lamp + add_signal(price=ctx.price() 或 None, message=msg)
        #          + task["notify"]==1 时 send_fn(文案)
        # 文案: f"【盯盘】{name} {买入|卖出}灯{亮|灭}：{msg}（YYYY-MM-DD HH:MM）"
    def run(self) -> None   # while True: tick(); sleep 到下一分钟边界
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_monitor_daemon.py
import pandas as pd
from monitor.daemon import MonitorDaemon, edge_transition, in_trading_hours
from monitor.store import MonitorStore


def test_edge_transition():
    assert edge_transition("buy", 0, True) == "buy_on"
    assert edge_transition("buy", 1, False) == "buy_off"
    assert edge_transition("buy", 1, True) is None
    assert edge_transition("buy", 0, False) is None
    assert edge_transition("sell", 1, None) is None


def test_in_trading_hours():
    import datetime as dt
    def ms(h, m):  # 北京时间
        return int(dt.datetime(2026, 9, 7, h, m).timestamp() * 1000)  # 周一
    assert in_trading_hours(ms(10, 0)) and in_trading_hours(ms(14, 30))
    assert not in_trading_hours(ms(12, 0)) and not in_trading_hours(ms(9, 0))


def _mk(tmp_path, script):
    st = MonitorStore(tmp_path / "m.db")
    tid = st.add_task("t1", "600869.SH", script, interval_sec=60, notify=1)
    day = pd.DataFrame({"timestamp": [1000], "open": [1.0], "high": [1.0],
                        "low": [1.0], "close": [11.0], "volume": [100],
                        "amount": [1100.0]})
    dc = type("DC", (), {"get_klines": lambda s, *a, **k: day})()
    fs = type("FS", (), {"get": lambda s, *a, **k: pd.Series([1.0], index=[1000])})()
    return st, tid, dc, fs


def test_tick_edge_notifies(tmp_path, monkeypatch):
    st, tid, dc, fs = _mk(tmp_path, 'def check(ctx):\n    return {"buy": True, "msg": "go"}\n')
    sent = []
    d = MonitorDaemon(st, dc, fs, send_fn=sent.append)
    import datetime as dt
    now = int(dt.datetime(2026, 9, 7, 10, 0).timestamp() * 1000)
    monkeypatch.setattr("monitor.daemon.in_trading_hours", lambda ts: True)
    d.tick(now)
    t = st.get_task(tid)
    assert t["buy_on"] == 1 and t["poll_count"] == 1
    assert len(st.list_signals(tid)) == 1 and len(sent) == 1 and "买入灯亮" in sent[0]
    d.tick(now + 61_000)   # 条件仍满足：不重复通知
    assert len(sent) == 1 and len(st.list_signals(tid)) == 1


def test_tick_disabled_and_interval(tmp_path, monkeypatch):
    st, tid, dc, fs = _mk(tmp_path, 'def check(ctx):\n    return {"buy": True}\n')
    monkeypatch.setattr("monitor.daemon.in_trading_hours", lambda ts: True)
    import datetime as dt
    now = int(dt.datetime(2026, 9, 7, 10, 0).timestamp() * 1000)
    st.set_enabled(tid, 0)
    d = MonitorDaemon(st, dc, fs, send_fn=lambda t: None)
    d.tick(now)
    assert st.get_task(tid)["poll_count"] == 0     # disabled 跳过
    st.set_enabled(tid, 1)
    d.tick(now)
    assert st.get_task(tid)["poll_count"] == 1
    d.tick(now + 30_000)                            # interval 未到
    assert st.get_task(tid)["poll_count"] == 1


def test_tick_script_error_isolated(tmp_path, monkeypatch):
    st, tid, dc, fs = _mk(tmp_path, 'def check(ctx):\n    raise RuntimeError("boom")\n')
    monkeypatch.setattr("monitor.daemon.in_trading_hours", lambda ts: True)
    d = MonitorDaemon(st, dc, fs, send_fn=lambda t: None)
    d.tick()
    t = st.get_task(tid)
    assert t["error_count"] == 1 and "boom" in t["last_error"] and t["buy_on"] == 0
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现**。到期判断 `(now - (last_run_at or 0)) >= max(60, interval_sec)*1000`；通知文案按接口注释；`run()` 用 `time.sleep(60 - time.time() % 60)` 对齐分钟边界。
- [ ] **Step 4: 跑测试确认通过**。

---

### Task 5: 入口脚本 `scripts/monitor.py` + `scripts/monitor_cli.py`

**Files:**
- Create: `scripts/monitor.py`、`scripts/monitor_cli.py`
- Test: `tests/test_monitor_cli.py`

**Interfaces:**
- Consumes: 全部前序模块；`datacenter.DataCenter`、`factors.FactorStore`。
- Produces（CLI 供 Task 8 的 skill 调用）:

```bash
.venv/bin/python scripts/monitor.py                      # 启动守护进程（前台）
.venv/bin/python scripts/monitor_cli.py register --name N --symbol S \
    [--interval 60] [--no-notify] --script-file path.py  # → 打印 task_id
.venv/bin/python scripts/monitor_cli.py list             # 表格：id/灯/名称/symbol/interval/enabled/notify/错误
.venv/bin/python scripts/monitor_cli.py show <id>        # 详情 + script 全文
.venv/bin/python scripts/monitor_cli.py toggle <id>      # enabled 翻转，打印新状态
.venv/bin/python scripts/monitor_cli.py delete <id> --yes
```

- [ ] **Step 1: 写失败测试**（CLI 用 `tmp_path` 的 db 跑 register/list/toggle/delete 一圈；`monitor_cli.main(argv, db_path)` 支持注入 db_path 便于测试）:

```python
# tests/test_monitor_cli.py
from scripts.monitor_cli import main


def test_cli_roundtrip(tmp_path, capsys):
    db = str(tmp_path / "m.db")
    sf = tmp_path / "s.py"
    sf.write_text('def check(ctx):\n    return {"buy": True}\n')
    main(["register", "--name", "t", "--symbol", "600869.SH",
          "--script-file", str(sf)], db_path=db)
    out = capsys.readouterr().out
    assert "task_id=" in out
    main(["list"], db_path=db)
    assert "600869.SH" in capsys.readouterr().out
    main(["toggle", "1"], db_path=db)
    assert "enabled=0" in capsys.readouterr().out
    main(["delete", "1", "--yes"], db_path=db)
    main(["list"], db_path=db)
    assert "600869.SH" not in capsys.readouterr().out
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现**。`monitor.py`：`source ~/.zshrc` 由用户负责；构造 `DataCenter()`/`FactorStore(dc)`/`MonitorStore("data/monitor.db")`/`MonitorDaemon(...)`，打印启动横幅（任务数、Bark 配置有无）后 `daemon.run()`。`monitor_cli.py` 用 argparse 子命令，默认 `db_path="data/monitor.db"`。
- [ ] **Step 4: 跑测试确认通过**。

---

### Task 6: webui 后端 `/api/monitor/*`

**Files:**
- Create: `src/webui/monitor_api.py`
- Modify: `src/webui/app.py`（AppStores 加 monitor store；include router）
- Test: `tests/test_monitor_api.py`

**Interfaces:**
- Consumes: `MonitorStore`（Task 1）。
- Produces（前端 Task 7 依赖）:

| 端点 | 行为 |
|---|---|
| `GET /api/monitor/tasks` | `{"items": [task dict...]}`（list_tasks） |
| `POST /api/monitor/tasks` | body `{name, symbol, script, interval_sec=60, notify=1}` → `{"id": n}`；校验 script 能 `load_check`（spec §6），失败 400 |
| `PUT /api/monitor/tasks/{id}` | body 任意子集 `{name,symbol,script,interval_sec,notify}`；script 同样校验；任务不存在 404 |
| `POST /api/monitor/tasks/{id}/toggle` | enabled 翻转 → `{"enabled": 0|1}` |
| `DELETE /api/monitor/tasks/{id}` | → `{"ok": true}` |
| `GET /api/monitor/signals?task_id=&limit=` | `{"items": [...]}` ts 倒序 |

- [ ] **Step 1: 写失败测试**

```python
# tests/test_monitor_api.py
from fastapi.testclient import TestClient
from webui.app import create_app


def _client(tmp_path):
    (tmp_path / "klines").mkdir()
    return TestClient(create_app(tmp_path))


def test_monitor_crud(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/monitor/tasks", json={
        "name": "t1", "symbol": "600869.SH",
        "script": 'def check(ctx):\n    return {"buy": True}\n'})
    assert r.status_code == 200 and r.json()["id"] == 1
    items = c.get("/api/monitor/tasks").json()["items"]
    assert items[0]["symbol"] == "600869.SH" and items[0]["enabled"] == 1
    r = c.put("/api/monitor/tasks/1", json={"interval_sec": 120})
    assert r.status_code == 200
    assert c.post("/api/monitor/tasks/1/toggle").json()["enabled"] == 0
    assert c.delete("/api/monitor/tasks/1").json()["ok"] is True
    assert c.get("/api/monitor/tasks").json()["items"] == []


def test_monitor_bad_script_400(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/monitor/tasks", json={
        "name": "bad", "symbol": "X", "script": "x = 1"})
    assert r.status_code == 400


def test_monitor_404(tmp_path):
    c = _client(tmp_path)
    assert c.put("/api/monitor/tasks/99", json={"name": "x"}).status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现**：`monitor_api.py` 建 `APIRouter(prefix="/api/monitor")`，从 `request.app.state.stores.monitor` 取 store；`app.py` 的 `AppStores.__init__` 加 `self.monitor = MonitorStore(data_dir / "monitor.db")`（import 自 `monitor.store`），`create_app` 里 `app.include_router(monitor_router)`（局部 import，同现有模式）。
- [ ] **Step 4: 跑测试确认通过**。

---

### Task 7: 前端「盯盘」tab

**Files:**
- Create: `frontend/src/pages/MonitorBoard.tsx`
- Modify: `frontend/src/App.tsx`（加第三个 tab）、`frontend/src/api.ts`（加 6 个函数）
- Test: 无单测（沿用第六期做法）；验收 = `npm run build` 通过 + 人工冒烟

**Interfaces:**
- Consumes: Task 6 的 6 个端点。

- [ ] **Step 1: `api.ts` 加函数**

```typescript
// 追加到 frontend/src/api.ts（沿用现有 fetch 封装风格）
export interface MonitorTask {
  id: number; name: string; symbol: string; script: string;
  interval_sec: number; enabled: number; notify: number;
  buy_on: number; sell_on: number; poll_count: number;
  signal_count: number; error_count: number; last_error: string | null;
  last_run_at: number | null; created_at: number;
}
export interface MonitorSignal {
  id: number; task_id: number; ts: number; kind: string;
  price: number | null; message: string;
}
export const monitorTasks = () =>
  fetch("/api/monitor/tasks").then(r => r.json()) as Promise<{ items: MonitorTask[] }>;
export const createTask = (body: Partial<MonitorTask>) =>
  fetch("/api/monitor/tasks", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) }).then(r => r.json());
export const updateTask = (id: number, body: Partial<MonitorTask>) =>
  fetch(`/api/monitor/tasks/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) }).then(r => r.json());
export const toggleTask = (id: number) =>
  fetch(`/api/monitor/tasks/${id}/toggle`, { method: "POST" }).then(r => r.json());
export const deleteTask = (id: number) =>
  fetch(`/api/monitor/tasks/${id}`, { method: "DELETE" }).then(r => r.json());
export const monitorSignals = (taskId?: number) =>
  fetch(`/api/monitor/signals${taskId ? `?task_id=${taskId}` : ""}`)
    .then(r => r.json()) as Promise<{ items: MonitorSignal[] }>;
```

- [ ] **Step 2: 写 `MonitorBoard.tsx`**（antd `Table` 任务列表：买/卖灯用 `Badge status={on ? "warning" : "default"}` + 文字标签、enabled 用 `Switch`、操作列 [详情][删除]；下方 `Table` 信号历史（时间/kind 中文映射 buy_on→买入灯亮 等/price/message）；`Drawer` 详情：`Input` 名称、`InputNumber` interval（min 60）、`Switch` notify、`Input.TextArea` script（rows≥12，等宽字体）+ 保存按钮调 updateTask；顶部 [新建任务] 按钮开空 Drawer 调 createTask。挂载时 load，操作后 reload。kind 映射表：

```typescript
const KIND_LABEL: Record<string, string> = {
  buy_on: "买入灯亮", buy_off: "买入灯灭",
  sell_on: "卖出灯亮", sell_off: "卖出灯灭",
};
```

- [ ] **Step 3: `App.tsx` 加 tab**：TABS 数组加 `{ key: "monitor", label: "盯盘" }`，content 区加第三个 display 切换 div 挂 `<MonitorBoard />`。
- [ ] **Step 4: `cd frontend && npm run build` 通过**（TS 无错）。人工冒烟留到 Task 9。

---

### Task 8: 盯盘专家 skill + 脚本验证管线

**Files:**
- Create: `.claude/skills/monitor-expert/SKILL.md`
- Create: `scripts/validate_watch.py`
- Test: `tests/test_validate_watch.py`

**Interfaces:**
- Consumes: `runtime.load_check/run_check/MonitorContext`（Task 3）、`monitor_cli`（Task 5）。
- Produces:

```bash
# 注册前验证三段：语法 → 干跑 → 历史回放
source ~/.zshrc
.venv/bin/python scripts/validate_watch.py <script.py> <symbol> [--days 750]
# 输出：语法 OK / 干跑返回值 / 回放触发次数 + 最近 3 次触发日期
```

`validate_watch.py` 核心（回放用"日线近似 ctx"：price=当日收盘、daily(n)=截至当日窗口、factor 同口径、minute_bars=当日 1m 缓存有则给没有则空）：

```python
def replay_daily(script: str, symbol: str, dc, fs, days: int = 750) -> list[int]:
    """逐日评估 check，返回触发（buy 或 sell 为 True）的日期 ms 列表。"""
```

- [ ] **Step 1: 写失败测试**（fake dc/fs 喂 5 天数据，条件 `close > 10` 应触发其中已知天数）:

```python
# tests/test_validate_watch.py
import pandas as pd
from scripts.validate_watch import replay_daily


def test_replay_daily_counts_triggers():
    ts = [i * 86_400_000 for i in range(5)]
    df = pd.DataFrame({"timestamp": ts, "open": [1]*5, "high": [1]*5,
                       "low": [1]*5, "close": [9, 11, 9, 11, 11],
                       "volume": [1]*5, "amount": [1.0]*5})
    dc = type("DC", (), {"get_klines": lambda s, sym, p, a, b, adjust="forward":
                         df[df.timestamp <= b] if p == "1d" else df.iloc[0:0]})()
    fs = type("FS", (), {"get": lambda s, *a, **k: pd.Series(dtype=float)})()
    script = 'def check(ctx):\n    return {"buy": ctx.daily(5)["close"].iloc[-1] > 10}\n'
    hits = replay_daily(script, "X.SH", dc, fs, days=5)
    assert len(hits) == 3
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现 `validate_watch.py`**（compile 检查 → 真实/注入 dc 干跑 → replay_daily 打印次数与最近 3 次日期）。**注意**：回放里 `daily(n)` 需按"截至当日"切片，在 replay 内部构造轻量 ctx（可直接复用 `MonitorContext` 加可选 `asof_ms` 参数——Task 3 的 `MonitorContext.__init__(self, dc, fs, symbol, asof_ms=None)`，asof 存在时所有取数窗口右端=asof。Task 3 实现时带上这个参数，测试不变）。
- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 写 `.claude/skills/monitor-expert/SKILL.md`**，章节固定为：
  1. **职责**：自然语言 → check(ctx) 脚本 → 验证 → 注册/启停/诊断（spec §13 四件事）
  2. **边界**：只生成/注册脚本不改盯盘系统；拒绝任何下单/交易动作请求；纯提醒
  3. **工作流程**：澄清口径（给默认并写明）→ 生成脚本 → `validate_watch.py` 三段验证（回放触发次数给用户判断松紧）→ `monitor_cli.py register` → 告知 task_id 与灯语义
  4. **MonitorContext 契约**：spec §6 四方法签名 + 返回结构约定 + 「脚本不要自己写只提醒一次逻辑」（边沿去重是 daemon 的活）
  5. **数据/因子调用速查**：spec §13.1 两段代码原文（脚本内走 ctx；skill 侧可用 DataCenter/FactorStore；`import factors.factors` 必须）
  6. **示例脚本库**：spec §13.2 六个例子原文
  7. **数据约束防坑**：WS 无权限（1m 轮询）、分钟K 1 年深度、限流（分钟按只 60/分）、停牌无 bar、休市 intraday 空、时段判断用 minute_bars 最后一根时间戳（北京时间 = ts/1000+8h）
  8. **诊断手册**：用户说"没提醒"时按序排查：任务 enabled？last_error？poll_count 增长？（非交易时段/停牌）→ 信号历史（条件没边沿）→ notify 开关 → Bark 配置

---

### Task 9: 收尾 — 全量测试 + HELP.md + 冒烟指引

- [ ] **Step 1: 全量测试** `.venv/bin/python -m pytest tests/`，预期 200 + 本期新增 ≈ **215± 全绿**；失败则修复。
- [ ] **Step 2: 更新 HELP.md**：§4 八期行改为实现完成（模块清单/测试数）；§5 代码结构加 `src/monitor/`（store/runtime/notify/daemon 四行说明）与 `.claude/skills/monitor-expert/`；§9 常用命令加 `scripts/monitor.py`、`scripts/monitor_cli.py` 五个子命令、`scripts/validate_watch.py`。
- [ ] **Step 3: 前端生产构建** `cd frontend && npm run build`。
- [ ] **Step 4: 真实冒烟（人工，需交易时段）**：`source ~/.zshrc && .venv/bin/python scripts/monitor.py` 跑 10 分钟；用 monitor_cli 注册一个「现价 > 0」必亮灯任务，确认：灯亮 → 手机收到 Bark → 页面可见 → 信号历史有条目。非交易时段则用 `validate_watch.py` 干跑代替。
- [ ] **Step 5: 勾掉本计划全部 checkbox**（Commit 步无）。

---

## Self-Review 记录

- **Spec 覆盖核对**：§4 四模块→Task 1/2/3/4 ✅；§5 两表→Task 1 ✅；§5.1 配置→Task 2 ✅；§6 ctx 契约→Task 3 ✅（asof_ms 为回放需要，Task 3/8 注明）；§7 调度/边沿/软超时→Task 4 ✅（软超时简化为不实现计时——同进程 exec 无法硬超时，记录即可，不阻塞）；§8 Bark→Task 2 ✅；§9 webui 6 端点→Task 6/7 ✅；§11 测试矩阵→各 Task Step 1 ✅；§13 skill→Task 8 ✅；§12 边界→无任务（不做的事）。
- **类型一致性**：`MonitorStore` 方法名在 Task 1 定义、Task 4/5/6 复用一致；`edge_transition("buy",...)` 返回 `buy_on` 与 signals.kind 取值一致；`MonitorContext(dc, fs, symbol, asof_ms=None)` 在 Task 3 与 Task 8 一致。
- **已知取舍**：软超时只留 spec 描述不实现（YAGNI）；cron/多进程不做；灯颜色用 Badge warning/default（不用红绿，避涨跌语义混淆）。
