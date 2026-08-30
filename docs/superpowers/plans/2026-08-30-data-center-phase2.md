# 数据中心第二期实现计划：复权 + 财务/元数据缓存 + 数据校验 + 日终维护

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已完成的第一期（K线缓存+回填）之上，补齐回测所需的全部数据能力：本地复权计算、财务/标的元数据/标的池缓存、数据质量校验、日终维护任务。

**Architecture:** 沿用第一期分层。新增 `adjust.py`（复权纯函数）、`store/financials.py`（财务 SQLite 表）、`quality.py`（校验）、`jobs/daily_maintenance.py`（日终任务）。MetaStore 增加 `ex_factors`、`fin_fetch_log`、`universes`/`universe_members` 表。

**Tech Stack:** 同第一期（tickflow SDK、DuckDB、pandas、SQLite、pytest）

**Spec:** `docs/superpowers/specs/2026-08-30-data-center-design.md` §4/§7/§8
**前置依赖:** `docs/superpowers/plans/2026-08-30-data-center-phase1.md` 已完成（MetaStore/KlineStore/TickFlowClient/DataCenter 存在）

---

## 关键设计约定

**复权（重要偏差说明）**：spec 原设计为所有复权类型本地计算。但 `forward_additive`/`backward_additive`（加法复权）需要每次分红的**现金金额**，而 ex-factors 接口只提供 `ex_factor` 比率。因此：
- `forward` / `backward`（乘性）：**本地计算**（默认路径，零网络）
- `none`：直接返回原始价
- `forward_additive` / `backward_additive`：**穿透回源**（服务端计算），结果**不缓存**（前复权加法同样随时间失效）。回测请用 `forward`，加法复权仅作核对用途

**因子语义待校准**：`ex_factor` 的精确定义（乘还是除、累积方向）由数据源决定，文档未明说。Task 1 用服务端复权结果作为 ground truth 对拍校准，校准结论写入 `docs/sdk-notes.md`，`adjust.py` 按校准后的公式实现。计划中测试用例按"乘性、前复权 = 历史价 × 后续因子累积积"的假设编写，若校准结果相反，实现时翻转即可，测试结构不变。

**成交量调整**：价格乘性复权时，`volume` 除以同一因子（保持 `amount ≈ price × volume` 一致），`amount` 不调整。

**财务表缓存语义**：财务记录按 `(symbol, period_end)` 唯一，公告后不可变 → 永久缓存。`fin_fetch_log(symbol, table, fetched_at)` 记录每个 symbol 每张表的完整拉取时间；`latest=True` 查询若 `fetched_at` 超过 24h 则回源刷新，否则走本地。

**交易日历**：不引入外部依赖——用已落库的上证指数 `000001.SH` 日线 timestamp 集合作为交易日历（回填已含指数；若无则回源拉取）。

---

### Task 1: ex_factors 存储 + 客户端方法 + 因子语义校准

**Files:**
- Modify: `src/datacenter/store/meta.py`（加 ex_factors 表与方法）
- Modify: `src/datacenter/client/tickflow_client.py`（加 get_ex_factors）
- Create: `scripts/calibrate_adjust.py`
- Create: `docs/sdk-notes.md` 追加（若已存在）
- Test: `tests/test_meta.py`、`tests/test_tickflow_client.py` 追加

- [ ] **Step 1: 写失败测试**

`tests/test_meta.py` 追加：

```python
def test_ex_factors_roundtrip(meta):
    meta.upsert_ex_factors("600000.SH", [(1700000000000, 0.95), (1710000000000, 0.92)])
    assert meta.get_ex_factors("600000.SH") == [(1700000000000, 0.95), (1710000000000, 0.92)]
    meta.upsert_ex_factors("600000.SH", [(1700000000000, 0.95)])  # 幂等去重
    assert len(meta.get_ex_factors("600000.SH")) == 2
    assert meta.get_ex_factors("000001.SZ") == []
```

`tests/test_tickflow_client.py` 追加：

```python
def test_get_ex_factors(fake_tf):
    fake_tf.klines.ex_factors.set([(1700000000000, 0.95)])
    client = make_client(fake_tf)
    assert client.get_ex_factors("600000.SH") == [(1700000000000, 0.95)]
```

conftest.py 加 `FakeExFactors`：`set(rows)` 预设、`.get(symbol)` 返回 `[{"timestamp": ts, "ex_factor": f}, ...]`；**实例挂在 `FakeKlines` 上**（`FakeKlines.__init__` 里 `self.ex_factors = FakeExFactors()`），使 fake 的属性路径与 client 的调用路径 `tf.klines.ex_factors` 严格一致。

**贯穿本计划的规则**：每新增一个 SDK 触点（ex_factors / instruments / financials / intraday），Fake  counterpart 在同一任务内加入 conftest，且 fake 属性路径 == client 调用路径。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_meta.py tests/test_tickflow_client.py -v`
Expected: 新测试 FAIL

- [ ] **Step 3: 实现**

meta.py 的 `_SCHEMA` 追加：

```sql
CREATE TABLE IF NOT EXISTS ex_factors (
    symbol TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    ex_factor REAL NOT NULL,
    PRIMARY KEY (symbol, ts_ms)
);
```

方法：

```python
    def upsert_ex_factors(self, symbol: str, factors: list[tuple[int, float]]) -> None:
        self._conn.executemany(
            "INSERT OR IGNORE INTO ex_factors (symbol, ts_ms, ex_factor) VALUES (?,?,?)",
            [(symbol, ts, f) for ts, f in factors])
        self._conn.commit()

    def get_ex_factors(self, symbol: str) -> list[tuple[int, float]]:
        return [(r[0], r[1]) for r in self._conn.execute(
            "SELECT ts_ms, ex_factor FROM ex_factors WHERE symbol=? ORDER BY ts_ms", (symbol,))]
```

tickflow_client.py 追加：

```python
    def get_ex_factors(self, symbol: str) -> list[tuple[int, float]]:
        """返回 [(除权日ms, ex_factor), ...] 按时间升序。"""
        data = self._call(self._tf.klines.ex_factors, symbol)
        rows = data if isinstance(data, list) else data.get("data", [])
        return sorted((int(r["timestamp"]), float(r["ex_factor"])) for r in rows)
```

注意：SDK 的 ex-factors 调用形态（`tf.klines.ex_factors(symbol)` 还是 `tf.ex_factors.get(symbol)`）以 Task 1 探测/scripts 实测为准，实现时先 `dir(tf.klines)` 确认。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_meta.py tests/test_tickflow_client.py -v`
Expected: 全 passed

- [ ] **Step 5: 因子语义校准（真实回源）**

`scripts/calibrate_adjust.py`：取 600000.SH 近 3 年日线，分别用 `adjust="none"` 和 `adjust="forward"` 回源，同时拉 ex-factors；验证哪种本地公式能复现服务端前复权结果：

```python
"""校准 ex_factor 语义：本地公式 vs 服务端 forward 复权对拍。
运行: uv run python scripts/calibrate_adjust.py
"""
import numpy as np
from tickflow import TickFlow

tf = TickFlow()
raw = tf.klines.get("600000.SH", period="1d", count=800, adjust="none", as_dataframe=True)
fwd = tf.klines.get("600000.SH", period="1d", count=800, adjust="forward", as_dataframe=True)
factors = tf.klines.ex_factors("600000.SH")  # 形态以实际为准
print("factors 样例:", factors[:3] if isinstance(factors, list) else factors)

merged = raw[["timestamp", "close"]].merge(
    fwd[["timestamp", "close"]], on="timestamp", suffixes=("_raw", "_fwd"))
merged["ratio"] = merged["close_fwd"] / merged["close_raw"]
print(merged.tail(20))
# 观察: ratio 是否在除权日跳变、最新日 ratio 是否 == 1（前复权特征）
# 再用因子累积积拟合 ratio，确认 乘/除 与 累积方向，结论写入 docs/sdk-notes.md
```

Run: `uv run python scripts/calibrate_adjust.py`，把结论（公式形式、与服务端结果的最大误差）写入 `docs/sdk-notes.md`。

- [ ] **Step 6: Commit**

```bash
git add src/datacenter/store/meta.py src/datacenter/client/tickflow_client.py scripts/calibrate_adjust.py docs/sdk-notes.md tests/
git commit -m "feat: ex-factors storage + client method + adjust semantics calibration"
```

---

### Task 2: adjust.py 复权计算

**Files:**
- Create: `src/datacenter/adjust.py`
- Test: `tests/test_adjust.py`

- [ ] **Step 1: 写失败测试**

`tests/test_adjust.py`：

```python
import numpy as np
import pandas as pd

from datacenter.adjust import apply_adjust
from tests.conftest import make_kline_df

DAY = 86_400_000
T0 = 1700000000000


def _df_with_closes(closes, start=T0):
    n = len(closes)
    df = make_kline_df("600000.SH", start, n, DAY)
    df["close"] = df["open"] = df["high"] = df["low"] = closes
    df["volume"] = 1000
    return df


def test_none_returns_raw():
    df = _df_with_closes([10.0, 10.0, 10.0])
    out = apply_adjust(df, [], "none")
    pd.testing.assert_frame_equal(out, df)


def test_forward_adjust_multiplies_history():
    """除权日在第 3 根（T0+2D），因子 0.5：前两根价格×0.5，量÷0.5，当日及以后不变。"""
    df = _df_with_closes([10.0, 10.0, 5.0])  # 10->5 除权
    factors = [(T0 + 2 * DAY, 0.5)]
    out = apply_adjust(df, factors, "forward")
    assert list(out["close"]) == [5.0, 5.0, 5.0]
    assert list(out["volume"]) == [2000, 2000, 1000]


def test_backward_adjust_scales_future():
    """后复权：历史不变，除权日及以后 ÷因子（价格抬高回去）。"""
    df = _df_with_closes([10.0, 10.0, 5.0])
    factors = [(T0 + 2 * DAY, 0.5)]
    out = apply_adjust(df, factors, "backward")
    assert list(out["close"]) == [10.0, 10.0, 10.0]


def test_multiple_ex_dates_cumulative():
    df = _df_with_closes([10.0, 8.0, 5.0])
    factors = [(T0 + DAY, 0.8), (T0 + 2 * DAY, 0.625)]  # 两次除权
    out = apply_adjust(df, factors, "forward")
    assert np.isclose(out["close"].iloc[0], 10.0 * 0.8 * 0.625)
    assert np.isclose(out["close"].iloc[1], 8.0 * 0.625)
    assert np.isclose(out["close"].iloc[2], 5.0)


def test_empty_factors_is_identity():
    df = _df_with_closes([10.0, 11.0])
    out = apply_adjust(df, [], "forward")
    pd.testing.assert_frame_equal(out, df)
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_adjust.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现**

`src/datacenter/adjust.py`（按 Task 1 校准结论实现；以下为"乘性、因子<1"假设的版本）：

```python
import numpy as np
import pandas as pd

PRICE_COLS = ["open", "high", "low", "close"]


def apply_adjust(df: pd.DataFrame, factors: list[tuple[int, float]], adjust: str) -> pd.DataFrame:
    """对原始价 DataFrame 应用复权。factors: [(除权日ms, ex_factor)] 升序。

    forward  （前复权）: 除权日之前的 bar，价格 × 该日及之后所有因子之积
    backward （后复权）: 除权日及之后的 bar，价格 ÷ 该日及之前所有因子之积
    volume 反向调整（除以价格因子），amount 不变。
    """
    if adjust == "none" or df.empty or not factors:
        return df
    if adjust not in ("forward", "backward"):
        raise ValueError(f"adjust {adjust!r} 不支持本地计算（additive 类型请穿透回源）")
    out = df.copy()
    ts = out["timestamp"].to_numpy()
    cum = np.ones(len(out))
    for ex_ts, factor in sorted(factors):
        if adjust == "forward":
            cum[ts < ex_ts] *= factor
        else:
            cum[ts >= ex_ts] /= factor
    for col in PRICE_COLS:
        out[col] = out[col] * cum
    out["volume"] = (out["volume"] / cum).round().astype("int64")
    return out
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_adjust.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacenter/adjust.py tests/test_adjust.py
git commit -m "feat: local forward/backward adjustment"
```

---

### Task 3: get_klines 集成复权 + 真实数据对拍

**Files:**
- Modify: `src/datacenter/api.py`
- Modify: `src/datacenter/resolver.py`（ensure_ex_factors）
- Test: `tests/test_api.py` 追加

- [ ] **Step 1: 写失败测试**

`tests/test_api.py` 追加：

```python
def test_get_klines_forward_adjust(dc):
    dc_, fake = dc  # fixture 已预置 10 根日线，close 恒为 C = base+0.5
    fake.klines.ex_factors.set([(T0 + 5 * DAY, 0.5)])  # 第 6 根为除权日
    df = dc_.get_klines("600000.SH", "1d", T0, T0 + 10 * DAY, adjust="forward")
    c = make_kline_df("600000.SH", T0, 1, DAY)["close"].iloc[0]  # 原始价 C
    assert df["close"].iloc[0] == pytest.approx(c * 0.5)   # 除权日前 ×0.5
    assert df["close"].iloc[4] == pytest.approx(c * 0.5)
    assert df["close"].iloc[5] == pytest.approx(c)         # 除权日起不变
    assert df["close"].iloc[-1] == pytest.approx(c)
```

```python
def test_get_klines_additive_falls_through_to_remote(dc):
    dc_, fake = dc
    fake.klines.queue(make_kline_df("600000.SH", T0, 10, DAY))
    df = dc_.get_klines("600000.SH", "1d", T0, T0 + 10 * DAY, adjust="forward_additive")
    assert len(df) == 10
    # 穿透回源：adjust 参数原样传给远程，不读缓存
    assert fake.klines.calls[-1]["adjust"] == "forward_additive"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_api.py -v`
Expected: 新测试 FAIL

- [ ] **Step 3: 实现**

resolver.py 追加：

```python
    def ensure_ex_factors(self, symbol: str) -> list[tuple[int, float]]:
        """因子不可变：本地有就直接用；没有则回源一次并永久缓存。
        注意：'没有'可能是真没有（从未除权），用 ex_factor_synced 标记防打空。"""
        if self._meta.get_meta_flag(f"exf:{symbol}"):
            return self._meta.get_ex_factors(symbol)
        factors = self._client.get_ex_factors(symbol)
        self._meta.upsert_ex_factors(symbol, factors)
        self._meta.set_meta_flag(f"exf:{symbol}")
        return factors
```

meta.py 加通用 kv 表：

```sql
CREATE TABLE IF NOT EXISTS meta_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```
方法 `get_meta_flag(key) -> bool`、`set_meta_flag(key)`（value 存时间戳）。

api.py 的 `get_klines` 增加 `adjust: str = "forward"` 参数：

```python
    def get_klines(self, symbol, period="1d", start_ms=None, end_ms=None, adjust="forward"):
        if adjust in ("forward_additive", "backward_additive"):
            # 加法复权穿透回源，不缓存（见计划"关键设计约定"）
            end_ms = end_ms or int(time.time() * 1000)
            start_ms = start_ms or end_ms - THREE_YEARS_MS
            return self.client.get_klines_range(symbol, period, start_ms, end_ms, adjust=adjust)
        ...原逻辑取原始价...
        df = self.klines.read([symbol], period, start_ms, end_ms)
        if adjust != "none" and not df.empty:
            factors = self.resolver.ensure_ex_factors(symbol)
            df = apply_adjust(df, factors, adjust)
        return df
```

`TickFlowClient.get_klines_range` 增加 `adjust="none"` 参数透传（小改）。

- [ ] **Step 4: 运行确认通过 + 真实对拍**

Run: `uv run pytest tests/test_api.py -v` → 全 passed

真实对拍（手动）：本地 `adjust="forward"` vs 服务端 `adjust="forward"` 在 600000.SH 上逐行比较，误差 < 1e-6。写进 `docs/sdk-notes.md`。

- [ ] **Step 5: Commit**

```bash
git add src/datacenter/api.py src/datacenter/resolver.py src/datacenter/store/meta.py src/datacenter/client/tickflow_client.py tests/
git commit -m "feat: adjust integrated into get_klines, verified against server-side forward"
```

---

### Task 4: 财务数据缓存（5 张表）

**Files:**
- Modify: `src/datacenter/client/tickflow_client.py`
- Create: `src/datacenter/store/financials.py`
- Modify: `src/datacenter/api.py`（get_financials）
- Test: `tests/test_financials.py`

缓存键 `(symbol, period_end)`；`fin_fetch_log(symbol, table, fetched_at)` 控制 latest 刷新（TTL 24h）。表结构不手写 DDL——pandas `to_sql` 动态建表，读取用 SQL 查询，避免 openapi 字段变更时改代码。

- [ ] **Step 1: 写失败测试**

`tests/test_financials.py`：

```python
import pandas as pd
import pytest
from datacenter import DataCenter
from tests.conftest import FakeTickFlow

INCOME_ROWS = [
    {"period_end": "2024-12-31", "revenue": 1e9, "net_income": 2e8},
    {"period_end": "2025-03-31", "revenue": 3e8, "net_income": 5e7},
]


class FakeFinancials:
    def __init__(self):
        self.calls = []
    def income(self, symbols, latest=False, as_dataframe=False):
        self.calls.append(dict(symbols=symbols, latest=latest))
        rows = [{**r, "symbol": s} for s in symbols for r in INCOME_ROWS]
        return pd.DataFrame(rows) if as_dataframe else rows


@pytest.fixture
def dc(tmp_path):
    fake = FakeTickFlow(symbols=["600000.SH"])
    fake.financials = FakeFinancials()
    return DataCenter(data_dir=tmp_path / "data", client_tf=fake), fake


def test_income_cached_after_first_fetch(dc):
    dc_, fake = dc
    df1 = dc_.get_financials("income", ["600000.SH"])
    df2 = dc_.get_financials("income", ["600000.SH"])
    assert len(df1) == 2 and len(df2) == 2
    assert len(fake.financials.calls) == 1  # 第二次走缓存


def test_latest_uses_cache_within_ttl(dc):
    dc_, fake = dc
    dc_.get_financials("income", ["600000.SH"], latest=True)
    dc_.get_financials("income", ["600000.SH"], latest=True)
    assert len(fake.financials.calls) == 1


def test_dedup_on_refetch(dc):
    dc_, fake = dc
    dc_.get_financials("income", ["600000.SH"])
    dc_.refresh_financials("income", ["600000.SH"])  # 强制刷新
    df = dc_.get_financials("income", ["600000.SH"])
    assert len(df) == 2  # 重复拉取不产生重复行
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_financials.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/datacenter/store/financials.py`：

```python
import time
from pathlib import Path
import pandas as pd

TABLES = {"income": "fin_income", "balance_sheet": "fin_balance",
          "cash_flow": "fin_cashflow", "metrics": "fin_metrics", "shares": "fin_shares"}
LATEST_TTL_SEC = 24 * 3600


class FinancialStore:
    """财务数据 SQLite 存储。表结构由数据驱动（to_sql 动态建表），(symbol, period_end) 去重。"""

    def __init__(self, db_path: str | Path):
        import sqlite3
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS fin_fetch_log ("
                           "symbol TEXT, tbl TEXT, fetched_at REAL, PRIMARY KEY (symbol, tbl))")
        self._conn.commit()

    def _fetched_at(self, symbol, table):
        row = self._conn.execute("SELECT fetched_at FROM fin_fetch_log WHERE symbol=? AND tbl=?",
                                 (symbol, table)).fetchone()
        return row[0] if row else None

    def needs_fetch(self, symbol, table, latest: bool) -> bool:
        ts = self._fetched_at(symbol, table)
        if ts is None:
            return True
        return latest and (time.time() - ts) > LATEST_TTL_SEC

    def save(self, table: str, df: pd.DataFrame) -> None:
        """DELETE + 追加 + 更新拉取日志，包在显式事务里（crash 不会留下"删了没插"的中间态）。
        注意：pandas to_sql 对 sqlite3 连接会自行 commit，故先 BEGIN IMMEDIATE 再由
        to_sql 的 commit 落盘，失败时显式 ROLLBACK。"""
        if df is None or df.empty:
            return
        tbl = TABLES[table]
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            keys = df[["symbol", "period_end"]].drop_duplicates()
            for _, r in keys.iterrows():
                self._conn.execute(f"DELETE FROM {tbl} WHERE symbol=? AND period_end=?",
                                   (r["symbol"], r["period_end"]))
            df.to_sql(tbl, self._conn, if_exists="append", index=False)
            now = time.time()
            self._conn.executemany(
                "INSERT INTO fin_fetch_log VALUES (?,?,?) ON CONFLICT(symbol, tbl)"
                " DO UPDATE SET fetched_at=excluded.fetched_at",
                [(s, table, now) for s in df["symbol"].unique()])
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def load(self, table: str, symbols: list[str], latest: bool) -> pd.DataFrame:
        tbl = TABLES[table]
        marks = ",".join("?" * len(symbols))
        try:
            df = pd.read_sql(f"SELECT * FROM {tbl} WHERE symbol IN ({marks})",
                             self._conn, params=symbols)
        except pd.errors.DatabaseError:
            return pd.DataFrame()
        if latest and not df.empty:
            df = (df.sort_values("period_end").groupby("symbol", as_index=False).tail(1))
        return df

    def close(self):
        self._conn.close()
```

client 追加（5 个表统一封装）：

```python
    def get_financials(self, table: str, symbols: list[str], latest: bool = False) -> pd.DataFrame:
        fn = getattr(self._tf.financials, table)
        return self._call(fn, symbols, latest=latest, as_dataframe=True)
```

api.py 追加：

```python
    def get_financials(self, table, symbols, latest=False):
        if isinstance(symbols, str):
            symbols = [symbols]
        need = [s for s in symbols if self.financials.needs_fetch(s, table, latest)]
        if need:
            df = self.client.get_financials(table, need, latest=False)  # 总是拉全量历史
            self.financials.save(table, df)
        return self.financials.load(table, symbols, latest)

    def refresh_financials(self, table, symbols):
        if isinstance(symbols, str):
            symbols = [symbols]
        df = self.client.get_financials(table, symbols, latest=False)
        self.financials.save(table, df)
```

`DataCenter.__init__` 加 `self.financials = FinancialStore(data_dir / "meta.db")`（与 MetaStore 共库不同表，WAL 支持）。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_financials.py -v`
Expected: 3 passed

- [ ] **Step 5: 真实回源 smoke + Commit**

```python
from datacenter import DataCenter
dc = DataCenter()
df = dc.get_financials("metrics", ["600519.SH", "000001.SZ"])
print(df)  # 验证真实字段
```

```bash
git add src/datacenter/store/financials.py src/datacenter/client/tickflow_client.py src/datacenter/api.py tests/test_financials.py
git commit -m "feat: financial data caching (5 tables, latest TTL refresh)"
```

---

### Task 5: 标的元数据与标的池完整缓存

**Files:**
- Modify: `src/datacenter/store/meta.py`
- Modify: `src/datacenter/client/tickflow_client.py`
- Modify: `src/datacenter/api.py`
- Test: `tests/test_meta.py`、`tests/test_api.py` 追加

- [ ] **Step 1: 写失败测试**

```python
def test_instrument_metadata_cached(tmp_path):
    fake = FakeTickFlow(symbols=["600000.SH"])
    fake.instruments = FakeInstruments({"600000.SH": {"symbol": "600000.SH", "name": "浦发银行",
                                        "exchange": "SH", "code": "600000", "region": "CN"}})
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    inst = dc.get_instruments(["600000.SH"])
    assert inst["600000.SH"]["name"] == "浦发银行"
    dc.get_instruments(["600000.SH"])  # 第二次不回源
    assert fake.instruments.calls == 1


def test_universe_members_cached(tmp_path):
    fake = FakeTickFlow(symbols=["a.SH", "b.SH"])
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    dc.list_symbols()  # 触发回源
    assert dc.get_universe_symbols("CN_Equity_A") == ["a.SH", "b.SH"]
```

（`FakeInstruments` 加进 conftest：`.batch(symbols)` 返回列表，`.calls` 计数。TTL：instruments/universe 元数据 24h 刷新，复用 meta_kv 存 fetched_at。）

- [ ] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**

实现要点：meta.py 的 instruments 表加 `name TEXT, type TEXT, region TEXT, ext_json TEXT` 列（`ALTER TABLE` 兼容或重建——第一期表若已上线，用 `ALTER TABLE instruments ADD COLUMN`）；universe_members 表 `(universe_id, symbol, PRIMARY KEY(universe_id, symbol))`；`get_instruments` / `get_universe_symbols` 走"本地缺失或超 24h 才回源"。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: instrument metadata + universe caching with TTL"
```

---

### Task 6: quality.py — 交易日历 + 连续性检查 + 缺口补拉

**Files:**
- Create: `src/datacenter/quality.py`
- Test: `tests/test_quality.py`

- [ ] **Step 1: 写失败测试**

```python
def test_trading_calendar_from_index(tmp_path):
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=FakeTickFlow())
    dc.klines.write(make_kline_df("000001.SH", T0, 5, DAY), "1d", tag="test")
    cal = trading_calendar(dc, T0, T0 + 5 * DAY)
    assert len(cal) == 5


def test_find_gaps_detects_missing_days(tmp_path):
    """一只股缺了中间两天 -> find_gaps 报出缺口区间。"""
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=FakeTickFlow())
    dc.klines.write(make_kline_df("000001.SH", T0, 5, DAY), "1d", tag="cal")
    df = make_kline_df("600000.SH", T0, 5, DAY)
    df = df.drop([1, 2])  # 挖洞
    dc.klines.write(df, "1d", tag="test")
    gaps = find_gaps(dc, "600000.SH", "1d", T0, T0 + 5 * DAY)
    assert gaps == [(T0 + DAY, T0 + 2 * DAY)]
```

（新股上市前/长期停牌的"缺口"属正常——`find_gaps` 只报，由调用方结合上市日期判断是否补拉。）

- [ ] **Step 2~4: 实现并通过**

`quality.py`：

```python
import pandas as pd


def trading_calendar(dc, start_ms: int, end_ms: int) -> set[int]:
    """以上证指数日线为交易日历。"""
    df = dc.get_klines("000001.SH", "1d", start_ms, end_ms, adjust="none")
    return set(df["timestamp"])


def find_gaps(dc, symbol: str, period: str, start_ms: int, end_ms: int) -> list[tuple[int, int]]:
    """对照交易日历找日线缺口，返回合并后的连续缺口区间（仅 period='1d' 有意义）。"""
    if period != "1d":
        raise ValueError("find_gaps 目前只支持 1d")
    cal = sorted(trading_calendar(dc, start_ms, end_ms))
    have = set(dc.get_klines(symbol, "1d", start_ms, end_ms, adjust="none")["timestamp"])
    missing = [t for t in cal if t not in have]
    # 按交易日历索引合并连续缺口
    idx = {t: i for i, t in enumerate(cal)}
    gaps = []
    for t in missing:
        if gaps and idx[t] == idx[gaps[-1][1]] + 1:
            gaps[-1] = (gaps[-1][0], t)
        else:
            gaps.append((t, t))
    return gaps


def repair_gaps(dc, symbol: str, gaps: list[tuple[int, int]]) -> None:
    """对每个缺口段强制回源补拉（绕过 coverage），并扩展覆盖区间。"""
    for gs, ge in gaps:
        df = dc.client.get_klines_range(symbol, "1d", gs - 86_400_000, ge + 86_400_000)
        dc.klines.write(df, "1d", tag="repair")
```

注意：coverage 语义是"已解析"，缺口在 coverage 之内，`resolver.ensure` 不会补拉，所以 `repair_gaps` 必须直接调 client（绕开 coverage）。这是有意设计，注释写明。

- [ ] **Step 5: Commit**

```bash
git add src/datacenter/quality.py tests/test_quality.py
git commit -m "feat: trading calendar + gap detection and repair"
```

---

### Task 7: quality.py — 抽样比对 + 1m/1d 交叉校验

**Files:**
- Modify: `src/datacenter/quality.py`
- Create: `scripts/validate.py`
- Test: `tests/test_quality.py` 追加

- [ ] **Step 1: 写失败测试**

```python
def test_sample_compare_detects_mismatch(tmp_path):
    fake = FakeTickFlow()
    fake.klines.queue(make_kline_df("600000.SH", T0, 5, DAY))  # 回源数据
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    local = make_kline_df("600000.SH", T0, 5, DAY)
    local.loc[0, "close"] = 999.0  # 本地被篡改
    dc.klines.write(local, "1d", tag="bad")
    dc.meta.extend_coverage("600000.SH", "1d", T0, T0 + 5 * DAY)
    bad = sample_compare(dc, ["600000.SH"], "1d", T0, T0 + 5 * DAY)
    assert bad == ["600000.SH"]


def test_minute_daily_cross_check(tmp_path):
    """1m 聚合 volume/amount 应等于当日 1d（容差 1%）。"""
    fake = FakeTickFlow()
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    # 构造当日 3 根 1m 线（volume=100/200/300, amount=1000/2000/3000）
    m1 = make_kline_df("600000.SH", T0, 3, 60_000)
    m1["volume"] = [100, 200, 300]
    m1["amount"] = [1000.0, 2000.0, 3000.0]
    dc.klines.write(m1, "1m", tag="test")
    # 当日 1d：volume=600, amount=6000 -> 一致
    d1 = make_kline_df("600000.SH", T0, 1, DAY)
    d1["volume"] = [600]
    d1["amount"] = [6000.0]
    dc.klines.write(d1, "1d", tag="test")
    assert cross_check_minute_daily(dc, "600000.SH", date_ms=T0) == []
    # 篡改 1d 的 volume -> 报不一致
    d2 = d1.copy()
    d2["volume"] = [9999]
    dc.klines.write(d2, "1d", tag="bad")  # 后写胜出
    mismatches = cross_check_minute_daily(dc, "600000.SH", date_ms=T0)
    assert mismatches == ["600000.SH"]
```

- [ ] **Step 2~4: 实现并通过**

实现要点：
- `sample_compare(dc, symbols, period, start, end, tol=1e-6)`：对给定 symbols 重新回源（绕过缓存），与本地逐 `(timestamp, close/volume)` 比对，返回不一致 symbol 列表
- `cross_check_minute_daily(dc, symbol, date_ms)`：读本地当日 1m，按 symbol 聚合 `volume.sum()/amount.sum()`，与当日 1d 行比对，容差 1%（集合竞价/数据源舍入差异）
- `scripts/validate.py`：CLI——随机抽 1% symbols 做 sample_compare + 对指定日期跑交叉校验，输出报告落 `job_reports` 表

- [ ] **Step 5: Commit**

```bash
git add src/datacenter/quality.py scripts/validate.py tests/test_quality.py
git commit -m "feat: sampling comparison + minute/daily cross validation"
```

---

### Task 8: 日终维护任务 + CLI

**Files:**
- Create: `src/datacenter/jobs/daily_maintenance.py`
- Create: `scripts/daily.py`
- Test: `tests/test_daily_maintenance.py`

日终四步（spec §7.2）：拉当日全市场日 K 固化 → 更新除权因子 → 刷新 instruments/标的池（超 TTL 的）→ 更新 coverage。产出报告。

- [ ] **Step 1: 写失败测试**

```python
def test_daily_maintenance_appends_and_updates(tmp_path):
    fake = FakeTickFlow(symbols=["a.SH", "b.SH"])
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    dc.list_symbols()
    # 预置历史覆盖：截至昨日
    dc.meta.extend_coverage("a.SH", "1d", T0, T0 + 5 * DAY)
    dc.meta.extend_coverage("b.SH", "1d", T0, T0 + 5 * DAY)
    # 今日数据（intraday/kline 接口回今日日K）
    fake.klines.queue(make_kline_df("a.SH", T0 + 6 * DAY, 1, DAY))
    fake.klines.queue(make_kline_df("b.SH", T0 + 6 * DAY, 1, DAY))
    # ex_factors 默认空（FakeKlines 自带 FakeExFactors()），无需设置
    report = run_daily_maintenance(dc, today_ms=T0 + 6 * DAY)
    assert report["symbols_updated"] == 2
    df = dc.get_klines("a.SH", "1d", T0 + 6 * DAY, T0 + 7 * DAY, adjust="none")
    assert len(df) == 1  # 当日已固化
```

- [ ] **Step 2~4: 实现并通过**

`daily_maintenance.py` 要点：

```python
def run_daily_maintenance(dc, today_ms=None) -> dict:
    """收盘后运行。幂等：重复跑不产生重复数据（last-wins 去重 + coverage 并集）。"""
    today_ms = today_ms or int(time.time() * 1000)
    # 北京时间当日 0 点的 ms 时间戳（Asia/Shanghai = UTC+8，与 KlineStore 分区口径一致；
    # 直接用 UTC 取模会有 8 小时边界错误）
    SH_OFFSET_MS = 8 * 3600_000
    day_start = today_ms - ((today_ms + SH_OFFSET_MS) % 86_400_000)
    symbols = dc.list_symbols()
    updated, failed = 0, {}
    for s in symbols:
        cov = dc.meta.get_coverage(s, "1d")
        start = (cov[1] + 1) if cov else day_start
        try:
            df = dc.client.get_klines_range(s, "1d", start, today_ms)
            if not df.empty:
                dc.klines.write(df, "1d", tag="daily")
            dc.meta.extend_coverage(s, "1d", start, today_ms)
            updated += 1
        except Exception as exc:
            failed[s] = str(exc)
    factors_updated = refresh_ex_factors(dc, symbols)   # 清 exf 标记后重拉有变化的
    refresh_metadata(dc)                                 # instruments/universes TTL 刷新
    report = {"symbols_updated": updated, "failed": failed, "ex_factors_checked": factors_updated}
    dc.meta.save_job_report("daily", report)
    return report
```

两个辅助函数的签名：

```python
def refresh_ex_factors(dc: DataCenter, symbols: list[str]) -> int:
    """逐 symbol 重新回源 ex-factors（upsert 幂等），返回检查过的数量。
    因子历史不可变，但新除权事件会追加，所以日终必须全量重拉每个 symbol。"""

def refresh_metadata(dc: DataCenter) -> None:
    """instruments 与标的池成员：距上次刷新超 24h（查 meta_kv 的 fetched_at）才回源。"""
```

meta.py 加 `job_reports(id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, report_json TEXT, created_at REAL)` 与 `save_job_report`。

- [ ] **Step 5: 真实 smoke + Commit**

收盘后跑一次 `uv run python scripts/daily.py`，验证当日数据落库、报告生成。

```bash
git add src/datacenter/jobs/daily_maintenance.py scripts/daily.py tests/test_daily_maintenance.py src/datacenter/store/meta.py
git commit -m "feat: daily maintenance job with reports"
```

---

### Task 9: README 更新 + 全量回归

- [ ] **Step 1: README 补充**：复权用法（`adjust="forward"` 默认）、财务接口用法、日终 cron 示例（`0 16 * * 1-5 cd /path && uv run python scripts/daily.py`）、校验命令
- [ ] **Step 2: `uv run pytest` 全量回归**，全部通过
- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: phase 2 usage (adjust, financials, daily cron, validation)"
```

---

## 完成标准（第二期 DoD）

1. `get_klines(adjust="forward")` 本地复权与服务端对拍误差 < 1e-6
2. 财务/元数据/标的池二次查询零网络请求
3. `validate.py` 对回填数据跑通：连续性缺口清单 + 1% 抽样比对报告
4. `daily.py` 幂等（连跑两次数据不重复）
5. 测试全绿，git 历史含每任务 commit
