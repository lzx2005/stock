# Web 查询界面（第六期）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 本地 Web 页面查询已存行情与因子数据——后端 FastAPI 只读离线，前端 React + antd + ECharts K 线图，分页 + 搜索。

**Architecture:** 后端 `src/webui/` 直接读存储层（KlineStore/MetaStore/FactorStore，`dc=None`），永不触发网络回源；前端 `frontend/` 为独立 Vite + React + TS + antd 应用，fetch `/api/*`（开发经 Vite proxy → 8666，生产构建后由 FastAPI 服务 `frontend/dist`）。数据层新增 4 个只读方法，全部带单测。

**Tech Stack:** 后端 `fastapi` + `uvicorn`；前端 `react@18` + `antd@5` + `echarts@5` + `vite@5` + `typescript@5`；测试 `pytest` + `httpx`（TestClient）。

**Spec:** `docs/superpowers/specs/2026-08-30-webui-design.md`

## Global Constraints

- **测试命令**：`.venv/bin/python -m pytest tests/`（配置 `--timeout=60`）。
- **不用 git**：所有 `Step N: Commit` 保持未勾，标注"（不执行，保持未勾）"；每完成一个 Step 立即 `- [ ]`→`- [x]`。
- **只读离线**：webui 只 import `datacenter.store.klines.KlineStore` / `datacenter.store.meta.MetaStore` / `factors.store.FactorStore`，**不 import** `datacenter.api.DataCenter` 与 `datacenter.client.*`；`FactorStore(None, root=...)`（只读方法不触碰 `self.dc`）。无需 `TICKFLOW_API_KEY`。
- **测试不联网**：合成 tmp 存储（`make_kline_df` / `KlineStore.write` / `MetaStore` / `FactorStore`），不依赖真实数据源。
- **分页约定**：`page` 从 1 起，`size` 默认 50、上限 2000；响应 `{total, page, size, items/rows, ...}`。
- **前端不做单测**（不引 vitest 工具链），交付前手动冒烟。
- 新依赖：后端运行 `fastapi>=0.110`、`uvicorn>=0.29`，dev `httpx>=0.27`；前端见 `frontend/package.json`。
- 时间戳为毫秒 int；`updated_at` 为 Unix 秒（前端 ×1000 格式化）。

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/datacenter/store/meta.py` | 加 `MetaStore.list_coverage` |
| `src/datacenter/store/klines.py` | 加 `KlineStore.count` |
| `src/factors/store.py` | 加 `FactorStore.list_stored` / `load_stored` |
| `src/webui/app.py` | `create_app(data_dir)` → FastAPI；挂 `/api`；生产挂 `frontend/dist` |
| `src/webui/api.py` | 全部 `/api` 端点（只读） |
| `scripts/serve.py` | 启动后端 `127.0.0.1:8666` |
| `frontend/**` | React + antd 前端（Vite） |
| `tests/test_meta.py` | `list_coverage` 用例 |
| `tests/test_kline_store.py` | `count` 用例 |
| `tests/test_factor_store.py` | `list_stored` / `load_stored` 用例 |
| `tests/test_webui.py` | API 端点用例（TestClient + 合成存储） |
| `pyproject.toml` | 加依赖与 `src/webui` 包 |
| `README.md` / `HELP.md` | P8 收尾更新 |

---

## Task 1: `MetaStore.list_coverage`

**Files:**
- Modify: `src/datacenter/store/meta.py`
- Test: `tests/test_meta.py`

**Interfaces:**
- Consumes: 现有 `kline_coverage` 表、`instruments` 表（已有 schema）
- Produces: `MetaStore.list_coverage(q=None, period=None, page=1, size=50) -> (total: int, rows: list[dict])`，row 形如 `{"symbol","code","name","period","start_ms","end_ms","updated_at"}`

- [x] **Step 1: 写失败测试**（追加到 `tests/test_meta.py`）

```python
def test_list_coverage_empty(meta):
    total, rows = meta.list_coverage()
    assert total == 0 and rows == []


def test_list_coverage_returns_rows(meta):
    meta.extend_coverage("600000.SH", "1d", 1000, 2000)
    meta.upsert_instruments([{"symbol": "600000.SH", "code": "600000", "name": "浦发银行"}])
    total, rows = meta.list_coverage()
    assert total == 1
    r = rows[0]
    assert r["symbol"] == "600000.SH" and r["period"] == "1d"
    assert r["start_ms"] == 1000 and r["end_ms"] == 2000
    assert r["code"] == "600000" and r["name"] == "浦发银行"


def test_list_coverage_search_and_period_filter(meta):
    meta.extend_coverage("600000.SH", "1d", 1000, 2000)
    meta.extend_coverage("000001.SZ", "1d", 1000, 2000)
    meta.extend_coverage("600000.SH", "5m", 1000, 2000)
    meta.upsert_instruments([{"symbol": "600000.SH", "code": "600000", "name": "浦发银行"}])
    total, rows = meta.list_coverage(q="600000")       # 按代码/symbol
    assert total == 2
    total, rows = meta.list_coverage(q="浦发")           # 按名称
    assert total == 2
    total, rows = meta.list_coverage(period="1d")      # 周期过滤
    assert total == 2
    total, rows = meta.list_coverage(q="nope")
    assert total == 0


def test_list_coverage_pagination(meta):
    for i, sym in enumerate(["a.SH", "b.SH", "c.SH", "d.SH"]):
        meta.extend_coverage(sym, "1d", 1000 + i, 2000 + i)
    total, rows = meta.list_coverage(page=2, size=2)
    assert total == 4 and [r["symbol"] for r in rows] == ["c.SH", "d.SH"]
```

- [x] **Step 2: 运行确认失败** → `.venv/bin/python -m pytest tests/test_meta.py -k list_coverage -v`，预期 FAIL（`AttributeError: 'MetaStore' object has no attribute 'list_coverage'`）

- [x] **Step 3: 实现**（追加到 `src/datacenter/store/meta.py`，`get_instrument` 之后）

```python
def list_coverage(self, q: str | None = None, period: str | None = None,
                  page: int = 1, size: int = 50) -> tuple[int, list[dict]]:
    """分页列出已存 K 线覆盖索引（LEFT JOIN instruments 取 code/name）。

    q 匹配 symbol/code/name（LIKE）；period 精确过滤。返回 (total, rows)，
    row 形如 {symbol, code, name, period, start_ms, end_ms, updated_at}。
    """
    page, size = max(1, page), max(1, size)
    where, args = [], []
    if period:
        where.append("c.period = ?")
        args.append(period)
    if q:
        pat = f"%{q}%"
        where.append("(c.symbol LIKE ? OR i.code LIKE ? OR i.name LIKE ?)")
        args += [pat, pat, pat]
    cond = f"WHERE {' AND '.join(where)}" if where else ""
    base = (f"FROM kline_coverage c LEFT JOIN instruments i ON i.symbol = c.symbol {cond}")
    total = self._conn.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
    rows = self._conn.execute(
        f"SELECT c.symbol, i.code, i.name, c.period, c.start_ms, c.end_ms, c.updated_at {base}"
        f" ORDER BY c.symbol ASC, c.period ASC LIMIT ? OFFSET ?",
        (*args, size, (page - 1) * size)).fetchall()
    return total, [
        {"symbol": r[0], "code": r[1], "name": r[2], "period": r[3],
         "start_ms": r[4], "end_ms": r[5], "updated_at": r[6]} for r in rows]
```

- [x] **Step 4: 运行确认通过** → `.venv/bin/python -m pytest tests/test_meta.py -k list_coverage -v`，PASS

- [ ] **Step 5: Commit**（不执行，保持未勾）

---

## Task 2: `KlineStore.count`

**Files:**
- Modify: `src/datacenter/store/klines.py`
- Test: `tests/test_kline_store.py`

**Interfaces:**
- Consumes: 现有 `read` 的过滤/去重语义
- Produces: `KlineStore.count(symbols: list[str], period: str, start_ms: int, end_ms: int) -> int`（与 `read` 同范围、同去重"后写胜出"的行数）

- [x] **Step 1: 写失败测试**（追加到 `tests/test_kline_store.py`）

```python
def test_count_matches_read(store):
    df = make_kline_df("600000.SH", T0, 10, DAY)
    store.write(df, "1d", tag="a")
    assert store.count(["600000.SH"], "1d", T0, T0 + 10 * DAY) == 10


def test_count_filters_range_and_dedup(store):
    df1 = make_kline_df("600000.SH", T0, 5, DAY)
    store.write(df1, "1d", tag="old")
    df2 = df1.copy()
    df2["close"] = 999.0                     # 修正数据后写，去重"后写胜出"
    store.write(df2, "1d", tag="fix")
    assert store.count(["600000.SH"], "1d", T0, T0 + 5 * DAY) == 5
    assert store.count(["600000.SH"], "1d", T0 + 2 * DAY, T0 + 3 * DAY) == 2


def test_count_empty_and_no_symbols(store):
    assert store.count(["600000.SH"], "1d", 0, 10**13) == 0
    assert store.count([], "1d", 0, 10**13) == 0
```

- [x] **Step 2: 运行确认失败** → `.venv/bin/python -m pytest tests/test_kline_store.py -k count -v`，预期 FAIL（`AttributeError: 'KlineStore' object has no attribute 'count'`）

- [x] **Step 3: 实现**（追加到 `src/datacenter/store/klines.py`，`read` 之后）

```python
def count(self, symbols: list[str], period: str,
          start_ms: int, end_ms: int) -> int:
    """K 线行数（与 read 同过滤/去重语义），供分页总数。纯读，不触发回源。"""
    if period not in ALL_PERIODS:
        raise ValueError(f"unknown period: {period}")
    if not symbols:
        return 0
    glob = str(self.root / f"period={period}" / "**" / "*.parquet")
    sql = """
        SELECT COUNT(*) FROM (
            SELECT symbol, timestamp
            FROM read_parquet(?, hive_partitioning=true, filename=true, union_by_name=true)
            WHERE symbol = ANY(?::VARCHAR[]) AND timestamp BETWEEN ? AND ?
              AND filename NOT LIKE '%/.tmp-%'
            QUALIFY row_number() OVER (
                PARTITION BY symbol, timestamp ORDER BY filename DESC
            ) = 1
        )
    """
    try:
        return int(duckdb.sql(sql, params=[glob, list(symbols), start_ms, end_ms]).fetchone()[0])
    except duckdb.IOException:
        return 0  # 尚无该周期数据
```

- [x] **Step 4: 运行确认通过** → `.venv/bin/python -m pytest tests/test_kline_store.py -k count -v`，PASS

- [ ] **Step 5: Commit**（不执行，保持未勾）

---

## Task 3: `FactorStore.list_stored` / `load_stored`

**Files:**
- Modify: `src/factors/store.py`
- Test: `tests/test_factor_store.py`（已有 `dc` fixture 与 `kdf`）

**Interfaces:**
- Consumes: 现有 `_path` / `_load`；`factor.json` 布局（`name/params/version/adjust/period/category/doc`）
- Produces:
  - `FactorStore.list_stored() -> list[dict]`，每指纹 `{"fingerprint","name","params","version","adjust","period","category","doc","cells","total_rows"}`；`cells: [{"symbol","period","rows"}]`
  - `FactorStore.load_stored(fingerprint, symbol, period) -> pd.Series`（索引=timestamp ms int，值=float；文件缺失返回空 Series）

- [x] **Step 1: 写失败测试**（追加到 `tests/test_factor_store.py`）

```python
def test_list_stored_and_load_stored(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)      # 落盘 ma n=5
    fs.get("a.SH", "ma", {"n": 20}, "1d", 100, 159)     # 另一指纹 ma n=20
    dirs = fs.list_stored()
    assert len(dirs) == 2
    d = next(x for x in dirs if x["params"] == {"n": 5})
    assert d["name"] == "ma" and d["version"] == 1 and d["adjust"] == "forward"
    assert d["cells"] == [{"symbol": "a.SH", "period": "1d", "rows": 60}]
    assert d["total_rows"] == 60
    s = fs.load_stored(d["fingerprint"], "a.SH", "1d")
    assert len(s) == 60 and s.index[0] == 100


def test_list_stored_and_load_stored_missing(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    assert fs.list_stored() == []
    assert fs.load_stored("deadbeef", "a.SH", "1d").empty
```

- [x] **Step 2: 运行确认失败** → `.venv/bin/python -m pytest tests/test_factor_store.py -k list_stored -v`，预期 FAIL（`AttributeError: 'FactorStore' object has no attribute 'list_stored'`）

- [x] **Step 3: 实现**（追加到 `src/factors/store.py`，`warm` 之后；文件头加 `import pyarrow.parquet as pq`）

```python
def list_stored(self) -> list[dict]:
    """枚举已存因子数据：扫 root/*/factor.json。每指纹含实际存在的
    symbol×period 组合（cells）与行数合计。纯读，不触发计算/回源。

    行数用 pyarrow parquet metadata（不读数据块），因子数据量小，全量统计。
    """
    if not self.root.exists():
        return []
    out = []
    for fp_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
        meta = fp_dir / "factor.json"
        if not meta.exists():
            continue
        try:
            info = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        cells = []
        for sym_dir in sorted(fp_dir.glob("symbol=*")):
            symbol = sym_dir.name[len("symbol="):]
            for period_dir in sorted(sym_dir.glob("period=*")):
                period = period_dir.name[len("period="):]
                part = period_dir / "part.parquet"
                if not part.exists():
                    continue
                try:
                    rows = pq.read_metadata(part).num_rows
                except Exception:
                    rows = 0
                cells.append({"symbol": symbol, "period": period, "rows": rows})
        out.append({
            "fingerprint": fp_dir.name,
            "name": info.get("name", ""),
            "params": info.get("params", {}),
            "version": info.get("version", 1),
            "adjust": info.get("adjust", self.adjust),
            "period": info.get("period", "1d"),
            "category": info.get("category", ""),
            "doc": info.get("doc", ""),
            "cells": cells,
            "total_rows": sum(c["rows"] for c in cells),
        })
    return out

def load_stored(self, fingerprint: str, symbol: str, period: str) -> pd.Series:
    """纯读已存因子值（索引=timestamp ms，值=value）。文件缺失返回空 Series。"""
    return self._load(self._path(fingerprint, symbol, period))
```

- [x] **Step 4: 运行确认通过** → `.venv/bin/python -m pytest tests/test_factor_store.py -k list_stored -v`，PASS；并跑全文件确认无回归：`.venv/bin/python -m pytest tests/test_factor_store.py -q`

- [ ] **Step 5: Commit**（不执行，保持未勾）

---

## Task 4: Web 后端（app.py + api.py + serve.py + pyproject + test_webui.py）

**Files:**
- Create: `src/webui/__init__.py`（空文件）
- Create: `src/webui/app.py`
- Create: `src/webui/api.py`
- Create: `scripts/serve.py`
- Create: `tests/test_webui.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: Task 1–3 的 `MetaStore.list_coverage` / `KlineStore.count` / `FactorStore.list_stored` / `load_stored`；`datacenter.constants.ALL_PERIODS`；`factors.factors`（import 即注册）
- Produces: `create_app(data_dir="data") -> FastAPI`；`scripts/serve.py` 可启动 `127.0.0.1:8666`

- [x] **Step 1: 装依赖** → 后端运行与测试依赖（二选一）：
  - uv：`uv add fastapi uvicorn` 且 `uv add --dev httpx`
  - pip：`.venv/bin/pip install "fastapi>=0.110" "uvicorn>=0.29" "httpx>=0.27"`

- [x] **Step 2: 更新 pyproject.toml**

```toml
dependencies = [
    "tickflow[all]>=0.1.17",
    "duckdb>=1.1",
    "pandas>=2.2",
    "pyarrow>=17",
    "fastapi>=0.110",
    "uvicorn>=0.29",
]

[dependency-groups]
dev = ["pytest>=8", "pytest-timeout>=2.3", "httpx>=0.27"]

[tool.hatch.build.targets.wheel]
packages = ["src/datacenter", "src/backtest", "src/factors", "src/webui"]
```

- [x] **Step 3: 实现 `src/webui/app.py`**

```python
"""Web 查询界面：FastAPI 应用工厂（离线只读）。

只读已存数据，不构造 TickFlowClient、不调 DataCenter——无需 API key、不触发网络回源。
生产模式：若 frontend/dist 存在，挂载静态资源并返回 index.html（需先 cd frontend && npm run build）。
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from datacenter.store.klines import KlineStore
from datacenter.store.meta import MetaStore
from factors.store import FactorStore


class AppStores:
    """后端持有的三个只读存储。webui 不 import DataCenter / datacenter.client。"""

    def __init__(self, data_dir: Path):
        self.klines = KlineStore(data_dir / "klines")
        self.meta = MetaStore(data_dir / "meta.db")
        self.factors = FactorStore(None, root=data_dir / "factors")


def create_app(data_dir: str | Path = "data") -> FastAPI:
    from webui.api import router  # 局部 import：api 内会注册内置因子

    app = FastAPI(title="本地行情/因子查询")
    app.state.stores = AppStores(Path(data_dir))
    app.include_router(router)

    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(dist / "index.html")

    return app
```

- [x] **Step 4: 实现 `src/webui/api.py`**

```python
"""Web 查询界面 API：全部只读端点。"""
import json

import pandas as pd
from fastapi import APIRouter, HTTPException, Request

from datacenter.constants import ALL_PERIODS
import factors.factors  # noqa: F401 —— import 即注册内置因子
from factors.registry import get_factor, list_factors

router = APIRouter(prefix="/api")

KLINE_COLS = ["timestamp", "open", "high", "low", "close", "volume", "amount"]


def _pagination(page: int, size: int) -> tuple[int, int]:
    return max(1, page), min(2000, max(1, size))


@router.get("/periods")
def periods():
    return {"items": list(ALL_PERIODS), "total": len(ALL_PERIODS),
            "page": 1, "size": len(ALL_PERIODS)}


@router.get("/coverage")
def coverage(request: Request, q: str = "", period: str = "",
             page: int = 1, size: int = 50):
    page, size = _pagination(page, size)
    total, rows = request.app.state.stores.meta.list_coverage(
        q or None, period or None, page, size)
    return {"total": total, "page": page, "size": size, "items": rows}


@router.get("/klines")
def klines(request: Request, symbol: str, period: str = "1d",
           start_ms: int | None = None, end_ms: int | None = None,
           page: int = 1, size: int = 50):
    page, size = _pagination(page, size)
    if period not in ALL_PERIODS:
        raise HTTPException(404, f"unknown period {period!r}")
    st = request.app.state.stores
    if start_ms is None or end_ms is None:
        cov = st.meta.get_coverage(symbol, period)
        if cov is None:
            return {"symbol": symbol, "period": period, "total": 0,
                    "page": page, "size": size, "rows": []}
        start_ms, end_ms = cov
    df = st.klines.read([symbol], period, start_ms, end_ms)
    total = st.klines.count([symbol], period, start_ms, end_ms)
    lo = (page - 1) * size
    page_df = df.iloc[lo:lo + size]
    return {"symbol": symbol, "period": period, "total": total,
            "page": page, "size": size,
            "rows": [list(r) for r in page_df[KLINE_COLS].itertuples(index=False)]}


@router.get("/factors")
def factors(request: Request, q: str = "", page: int = 1, size: int = 50):
    page, size = _pagination(page, size)
    stored = request.app.state.stores.factors.list_stored()
    by_name: dict[str, int] = {}
    for d in stored:
        by_name[d["name"]] = by_name.get(d["name"], 0) + 1
    items = []
    for name in sorted(list_factors()):   # 按 name 排序
        defn, params, _ = get_factor(name)
        if q and q.lower() not in name.lower() and q.lower() not in (defn.doc or "").lower():
            continue
        items.append({"name": name, "category": defn.category, "period": defn.period,
                      "version": defn.version, "default_params": params,
                      "doc": defn.doc, "stored_dir_count": by_name.get(name, 0)})
    total = len(items)
    return {"total": total, "page": page, "size": size,
            "items": items[(page - 1) * size:page * size]}


@router.get("/factor-dirs")
def factor_dirs(request: Request, q: str = "", page: int = 1, size: int = 50):
    page, size = _pagination(page, size)
    dirs = request.app.state.stores.factors.list_stored()
    if q:
        lq = q.lower()
        dirs = [d for d in dirs if lq in d["name"].lower()
                or lq in json.dumps(d["params"], ensure_ascii=False).lower()]
    dirs.sort(key=lambda d: (d["name"], json.dumps(d["params"], sort_keys=True, ensure_ascii=False)))
    total = len(dirs)
    return {"total": total, "page": page, "size": size,
            "items": dirs[(page - 1) * size:page * size]}


@router.get("/factor-values")
def factor_values(request: Request, fingerprint: str, symbol: str, period: str,
                  page: int = 1, size: int = 50):
    page, size = _pagination(page, size)
    series = request.app.state.stores.factors.load_stored(fingerprint, symbol, period)
    if series.empty:
        raise HTTPException(404, f"no stored factor data: {fingerprint}/{symbol}/{period}")
    total = len(series)
    part = series.iloc[(page - 1) * size:page * size]
    rows = [[int(ts), None if pd.isna(v) else float(v)] for ts, v in part.items()]
    return {"fingerprint": fingerprint, "symbol": symbol, "period": period,
            "total": total, "page": page, "size": size, "rows": rows}
```

- [x] **Step 5: 实现 `scripts/serve.py`**

```python
"""本地行情/因子查询服务。

用法：
  uv run python scripts/serve.py                 # 后端 8666（仅 /api）
  若需前端页面：先 cd frontend && npm run build，再启动本脚本（服务 dist，单进程访问 localhost:8666）
"""
from pathlib import Path

import uvicorn

from webui.app import create_app

if __name__ == "__main__":
    print(f"[webui] 数据目录: {Path('data').resolve()}")
    print("[webui] 访问 http://127.0.0.1:8666")
    app = create_app(data_dir="data")
    uvicorn.run(app, host="127.0.0.1", port=8666, log_level="info")
```

- [x] **Step 6: 写失败测试 `tests/test_webui.py`**（合成 tmp 存储，不联网）

```python
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from datacenter.store.klines import KlineStore
from datacenter.store.meta import MetaStore
from factors.store import FactorStore
from tests.conftest import make_kline_df
from webui.app import create_app

DAY = 86_400_000
T0 = 1754011800000  # 2025-08-01 09:30 Asia/Shanghai = 1754011800000 ms


class FakeDC:
    """只读假数据中心：get_klines 按范围切分合成数据（仅供 FactorStore.get 计算落盘）。"""
    def __init__(self, data):
        self.data = data
    def get_klines(self, symbol, period="1d", start_ms=None, end_ms=None, adjust="forward"):
        df = self.data.get(symbol, pd.DataFrame())
        if start_ms is not None:
            df = df[df["timestamp"] >= start_ms]
        if end_ms is not None:
            df = df[df["timestamp"] <= end_ms]
        return df.copy()


def _seed(tmp_path):
    """构造一个临时 data 目录：1 标的日线 10 根 + 覆盖记录 + 1 个已算因子(ma n=5)。"""
    data_dir = tmp_path / "data"
    (data_dir / "klines").mkdir(parents=True, exist_ok=True)
    kstore = KlineStore(data_dir / "klines")
    meta = MetaStore(data_dir / "meta.db")
    df = make_kline_df("600000.SH", T0, 10, DAY)
    kstore.write(df, "1d", tag="t")
    meta.extend_coverage("600000.SH", "1d", T0, T0 + 9 * DAY)
    meta.upsert_instruments([{"symbol": "600000.SH", "code": "600000", "name": "浦发银行"}])
    fs = FactorStore(FakeDC({"600000.SH": df}), root=data_dir / "factors")
    fs.get("600000.SH", "ma", {"n": 5}, "1d", T0, T0 + 9 * DAY)
    return data_dir


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(data_dir=_seed(tmp_path)))


def test_periods(client):
    r = client.get("/api/periods")
    assert r.status_code == 200
    assert "1d" in r.json()["items"]


def test_coverage_search_and_pagination(client):
    r = client.get("/api/coverage", params={"q": "600000"})
    body = r.json()
    assert body["total"] == 1 and body["items"][0]["symbol"] == "600000.SH"
    assert body["items"][0]["name"] == "浦发银行"
    assert client.get("/api/coverage", params={"q": "nope"}).json()["total"] == 0


def test_klines_paginated_and_default_range(client):
    r = client.get("/api/klines", params={"symbol": "600000.SH", "period": "1d", "page": 1, "size": 4})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 10 and len(body["rows"]) == 4
    assert body["rows"][0][0] == T0 and len(body["rows"][0]) == 7


def test_klines_bad_period_404(client):
    assert client.get("/api/klines", params={"symbol": "600000.SH", "period": "1x"}).status_code == 404


def test_klines_unknown_symbol_total_zero(client):
    body = client.get("/api/klines", params={"symbol": "NO.SH", "period": "1d"}).json()
    assert body["total"] == 0


def test_factors_registered_and_searchable(client):
    body = client.get("/api/factors", params={"q": "ma"}).json()
    assert body["total"] >= 1
    assert all("ma" in i["name"] for i in body["items"])
    assert any(i["stored_dir_count"] == 1 for i in body["items"] if i["name"] == "ma")


def test_factor_dirs_lists_cells(client):
    body = client.get("/api/factor-dirs").json()
    assert body["total"] == 1
    d = body["items"][0]
    assert d["name"] == "ma"
    assert d["cells"] == [{"symbol": "600000.SH", "period": "1d", "rows": 10}]
    assert d["total_rows"] == 10


def test_factor_values_paginated_and_404(client):
    fp = client.get("/api/factor-dirs").json()["items"][0]["fingerprint"]
    body = client.get("/api/factor-values",
                      params={"fingerprint": fp, "symbol": "600000.SH", "period": "1d", "size": 5}).json()
    assert body["total"] == 10 and len(body["rows"]) == 5
    assert client.get("/api/factor-values",
                      params={"fingerprint": "deadbeef", "symbol": "x", "period": "1d"}).status_code == 404
```

- [x] **Step 7: 运行确认失败** → `.venv/bin/python -m pytest tests/test_webui.py -v`，预期 FAIL（`ModuleNotFoundError: webui`）

- [x] **Step 8: 运行确认通过** → `.venv/bin/python -m pytest tests/test_webui.py -v`，全部 PASS（若 `httpx` 未装，先做 Step 1）

- [ ] **Step 9: Commit**（不执行，保持未勾）

---

## Task 5: 前端脚手架（Vite + React + TS + antd + api 封装 + 布局）

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/style.css`

**Interfaces:**
- Consumes: Task 4 的 `/api/*`（开发经 Vite proxy → 8666）
- Produces: 可 `npm run build` 出 `frontend/dist` 的 React 应用骨架（两空 tab 占位由 Task 6/7 填充）

- [x] **Step 1: `frontend/package.json`**

```json
{
  "name": "stock-webui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@ant-design/icons": "^5.4.0",
    "antd": "^5.21.0",
    "dayjs": "^1.11.13",
    "echarts": "^5.5.1",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.0"
  }
}
```

- [x] **Step 2: `frontend/vite.config.ts`**

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8666" },
  },
  build: { outDir: "dist" },
});
```

- [x] **Step 3: `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noFallthroughCasesInSwitch": true,
    "types": []
  },
  "include": ["src"]
}
```

- [x] **Step 4: `frontend/index.html`**

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>本地行情/因子查询</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [x] **Step 5: `frontend/src/main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import "./style.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN}>
      <App />
    </ConfigProvider>
  </React.StrictMode>
);
```

- [x] **Step 6: `frontend/src/style.css`**

```css
.row-selected {
  background: #e6f4ff !important;
}
body {
  margin: 0;
  padding: 16px;
  background: #f5f5f5;
}
```

- [x] **Step 7: `frontend/src/App.tsx`**

```tsx
import { Tabs } from "antd";
import KlineBrowser from "./pages/KlineBrowser";
import FactorBrowser from "./pages/FactorBrowser";

export default function App() {
  return (
    <Tabs
      defaultActiveKey="klines"
      items={[
        { key: "klines", label: "行情", children: <KlineBrowser /> },
        { key: "factors", label: "因子", children: <FactorBrowser /> },
      ]}
    />
  );
}
```

- [x] **Step 8: `frontend/src/api.ts`**

```ts
// 后端 API 封装（全部只读，服务端分页）
export interface Page<T> {
  total: number;
  page: number;
  size: number;
  items: T[];
}

export interface CoverageRow {
  symbol: string;
  code: string | null;
  name: string | null;
  period: string;
  start_ms: number;
  end_ms: number;
  updated_at: number;
}

export type KlineRow = [number, number, number, number, number, number, number];

export interface KlinesResp {
  symbol: string;
  period: string;
  total: number;
  page: number;
  size: number;
  rows: KlineRow[];
}

export interface FactorRow {
  name: string;
  category: string;
  period: string;
  version: number;
  default_params: Record<string, unknown>;
  doc: string;
  stored_dir_count: number;
}

export interface StoredCell {
  symbol: string;
  period: string;
  rows: number;
}

export interface FactorDir {
  fingerprint: string;
  name: string;
  params: Record<string, unknown>;
  version: number;
  adjust: string;
  period: string;
  category: string;
  doc: string;
  cells: StoredCell[];
  total_rows: number;
}

export interface FactorValuesResp {
  fingerprint: string;
  symbol: string;
  period: string;
  total: number;
  page: number;
  size: number;
  rows: [number, number | null][];
}

async function get<T>(path: string, params: Record<string, string | number | undefined>): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const url = `/api${path}${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      if (typeof j?.detail === "string") detail = j.detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(`请求失败(${res.status}): ${detail}`);
  }
  return res.json();
}

export const api = {
  periods: () => get<Page<string>>("/periods", {}),
  coverage: (q: string, period: string, page: number, size: number) =>
    get<Page<CoverageRow>>("/coverage", { q, period, page, size }),
  klines: (symbol: string, period: string, start_ms: number, end_ms: number, page: number, size: number) =>
    get<KlinesResp>("/klines", { symbol, period, start_ms, end_ms, page, size }),
  factors: (q: string, page: number, size: number) =>
    get<Page<FactorRow>>("/factors", { q, page, size }),
  factorDirs: (q: string, page: number, size: number) =>
    get<Page<FactorDir>>("/factor-dirs", { q, page, size }),
  factorValues: (fingerprint: string, symbol: string, period: string, page: number, size: number) =>
    get<FactorValuesResp>("/factor-values", { fingerprint, symbol, period, page, size }),
};
```

- [x] **Step 9: 安装前端依赖 + 验证构建** → `cd frontend && npm install && npm run build`，预期 `dist/` 生成且无 TypeScript 报错（`KlineBrowser`/`FactorBrowser` 尚未创建，`App.tsx` 引用会报"找不到模块"——**先创建空占位**）

```tsx
// frontend/src/pages/KlineBrowser.tsx（占位，Task 6 替换）
export default function KlineBrowser() {
  return <div>行情（待实现）</div>;
}
```

```tsx
// frontend/src/pages/FactorBrowser.tsx（占位，Task 7 替换）
export default function FactorBrowser() {
  return <div>因子（待实现）</div>;
}
```

- [x] **Step 10: 手动冒烟** → `cd frontend && npm run dev`，浏览器开 `localhost:5173`，看到 antd 两个 tab 均显示占位文案。

- [ ] **Step 11: Commit**（不执行，保持未勾）

---

## Task 6: 行情 tab（KlineBrowser + EChartsKline）

**Files:**
- Create: `frontend/src/components/EChartsKline.tsx`
- Replace: `frontend/src/pages/KlineBrowser.tsx`（覆盖 Task 5 占位）

**Interfaces:**
- Consumes: `api.coverage/periods/klines`；Task 5 的 `Page/CoverageRow/KlinesResp/KlineRow` 类型
- Produces: 完整行情 tab（覆盖索引表 + 点行下钻 K 线明细 + 图表 + 服务端分页）

- [x] **Step 1: `frontend/src/components/EChartsKline.tsx`**

```tsx
import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import dayjs from "dayjs";

export interface KlineBar {
  ts: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export default function EChartsKline({ bars, isMinute }: { bars: KlineBar[]; isMinute: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chartRef.current = echarts.init(ref.current);
    const onResize = () => chartRef.current?.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chartRef.current?.dispose();
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || bars.length === 0) return;
    chart.setOption(
      {
        animation: false,
        tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
        grid: { left: 60, right: 20, top: 20, bottom: 60 },
        xAxis: {
          type: "category",
          data: bars.map((b) =>
            isMinute ? dayjs(b.ts).format("MM-DD HH:mm") : dayjs(b.ts).format("YYYY-MM-DD")
          ),
          scale: true,
        },
        yAxis: { scale: true },
        dataZoom: [{ type: "inside" }, { type: "slider" }],
        series: [{ type: "candlestick", data: bars.map((b) => [b.o, b.c, b.l, b.h]) }],
      },
      true
    );
  }, [bars, isMinute]);

  return <div ref={ref} style={{ width: "100%", height: 420 }} />;
}
```

- [x] **Step 2: `frontend/src/pages/KlineBrowser.tsx`**（完整实现）

```tsx
import { useCallback, useEffect, useState } from "react";
import { DatePicker, Empty, Input, message, Select, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { api, CoverageRow, KlinesResp, KlineRow } from "../api";
import EChartsKline, { KlineBar } from "../components/EChartsKline";

const PAGE_SIZE = 50;
const CHART_MAX = 2000;
const MINUTE_PERIODS = new Set(["1m", "5m", "15m", "30m", "60m"]);

function fmt(ms: number, minute: boolean) {
  return minute ? dayjs(ms).format("YYYY-MM-DD HH:mm") : dayjs(ms).format("YYYY-MM-DD");
}

export default function KlineBrowser() {
  const [periods, setPeriods] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [period, setPeriod] = useState("");
  const [covPage, setCovPage] = useState(1);
  const [coverage, setCoverage] = useState<{ total: number; items: CoverageRow[] } | null>(null);
  const [covLoading, setCovLoading] = useState(false);

  const [selected, setSelected] = useState<CoverageRow | null>(null);
  const [range, setRange] = useState<[number, number] | null>(null);
  const [chartBars, setChartBars] = useState<KlineBar[]>([]);
  const [klines, setKlines] = useState<KlinesResp | null>(null);
  const [kLoading, setKLoading] = useState(false);
  const [kPage, setKPage] = useState(1);
  const [kSize, setKSize] = useState(PAGE_SIZE);

  useEffect(() => {
    api.periods().then((r) => setPeriods(r.items)).catch((e) => message.error(String(e.message)));
  }, []);

  const loadCoverage = useCallback((page: number, qv: string, pv: string) => {
    setCovLoading(true);
    api.coverage(qv, pv, page, PAGE_SIZE)
      .then((r) => { setCoverage(r); setCovPage(page); })
      .catch((e) => message.error(String(e.message)))
      .finally(() => setCovLoading(false));
  }, []);
  useEffect(() => { loadCoverage(1, q, period); }, [q, period, loadCoverage]);

  const loadKlines = useCallback((row: CoverageRow, page: number, size: number, rng: [number, number] | null) => {
    setKLoading(true);
    const [s, e] = rng ?? [row.start_ms, row.end_ms];
    api.klines(row.symbol, row.period, s, e, page, size)
      .then((r) => { setKlines(r); setKPage(page); setKSize(size); })
      .catch((err) => message.error(String(err.message)))
      .finally(() => setKLoading(false));
  }, []);

  const loadChart = useCallback((row: CoverageRow, rng: [number, number] | null) => {
    const [s, e] = rng ?? [row.start_ms, row.end_ms];
    api.klines(row.symbol, row.period, s, e, 1, CHART_MAX)
      .then((r) =>
        setChartBars(r.rows.map(([ts, o, h, l, c, v]) => ({ ts, o, h, l, c, v })))
      )
      .catch((err) => message.error(String(err.message)));
  }, []);

  const selectRow = (row: CoverageRow) => {
    setSelected(row);
    setRange(null);
    setKlines(null);
    setChartBars([]);
    loadKlines(row, 1, PAGE_SIZE, null);
    loadChart(row, null);
  };

  const minute = selected ? MINUTE_PERIODS.has(selected.period) : false;

  const covCols: ColumnsType<CoverageRow> = [
    { title: "代码", dataIndex: "symbol" },
    { title: "名称", dataIndex: "name", render: (v: string | null) => v ?? "-" },
    { title: "周期", dataIndex: "period" },
    { title: "起始", dataIndex: "start_ms", render: (v: number, r) => fmt(v, MINUTE_PERIODS.has(r.period)) },
    { title: "截止", dataIndex: "end_ms", render: (v: number, r) => fmt(v, MINUTE_PERIODS.has(r.period)) },
    { title: "更新时间", dataIndex: "updated_at", render: (v: number) => dayjs(v * 1000).format("YYYY-MM-DD HH:mm") },
  ];

  const kCols: ColumnsType<KlineRow> = [
    { title: "时间", render: (_, r) => fmt(r[0], minute) },
    { title: "开", render: (_, r) => r[1] },
    { title: "高", render: (_, r) => r[2] },
    { title: "低", render: (_, r) => r[3] },
    { title: "收", render: (_, r) => r[4] },
    { title: "量", render: (_, r) => r[5] },
    { title: "额", render: (_, r) => r[6] },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Space wrap>
        <Input.Search
          placeholder="搜索代码/名称"
          allowClear
          onSearch={(v) => setQ(v.trim())}
          style={{ width: 220 }}
        />
        <Select
          placeholder="周期"
          allowClear
          style={{ width: 120 }}
          value={period || undefined}
          onChange={(v) => setPeriod(v ?? "")}
          options={periods.map((p) => ({ value: p, label: p }))}
        />
      </Space>

      <Table
        rowKey={(r) => `${r.symbol}|${r.period}`}
        size="small"
        loading={covLoading}
        dataSource={coverage?.items ?? []}
        columns={covCols}
        rowClassName={(r) =>
          selected?.symbol === r.symbol && selected?.period === r.period ? "row-selected" : ""
        }
        onRow={(r) => ({ onClick: () => selectRow(r), style: { cursor: "pointer" } })}
        pagination={{
          current: covPage,
          pageSize: PAGE_SIZE,
          total: coverage?.total ?? 0,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p) => loadCoverage(p, q, period),
        }}
      />

      {selected && (
        <div>
          <Typography.Title level={5}>
            {selected.symbol} · {selected.period}
          </Typography.Title>
          <Space wrap style={{ marginBottom: 8 }}>
            <Typography.Text type="secondary">日期范围（缺省=已存覆盖区间）</Typography.Text>
            <DatePicker.RangePicker
              onChange={(dates) => {
                const rng =
                  dates && dates[0] && dates[1]
                    ? [dates[0].startOf("day").valueOf(), dates[1].endOf("day").valueOf()]
                    : null;
                setRange(rng);
                setKlines(null);
                setKPage(1);
                loadKlines(selected, 1, kSize, rng);
                loadChart(selected, rng);
              }}
            />
          </Space>
          {chartBars.length > 0 ? (
            <EChartsKline bars={chartBars} isMinute={minute} />
          ) : (
            <Empty description="该区间无数据" style={{ margin: "24px 0" }} />
          )}
          <Table
            rowKey={(r) => String(r[0])}
            size="small"
            loading={kLoading}
            dataSource={klines?.rows ?? []}
            columns={kCols}
            pagination={{
              current: kPage,
              pageSize: kSize,
              total: klines?.total ?? 0,
              showSizeChanger: true,
              pageSizeOptions: [20, 50, 100, 200],
              showTotal: (t) => `共 ${t} 根`,
              onChange: (p, ps) => { if (selected) loadKlines(selected, p, ps, range); },
            }}
          />
        </div>
      )}
    </Space>
  );
}
```

- [x] **Step 3: 验证** → `cd frontend && npm run build`（无 TS 报错）；后端 `uv run python scripts/serve.py` + 前端 `npm run dev`，浏览器冒烟：
  - 行情 tab 搜索 `600000` → 覆盖表出现该标的行
  - 点击行 → K 线图渲染 + 明细表分页正常
  - 改日期范围 → 图与表随范围刷新

- [ ] **Step 4: Commit**（不执行，保持未勾）

---

## Task 7: 因子 tab（FactorBrowser）

**Files:**
- Replace: `frontend/src/pages/FactorBrowser.tsx`（覆盖 Task 5 占位）

**Interfaces:**
- Consumes: `api.factors/factorDirs/factorValues`；`FactorRow/FactorDir/StoredCell/FactorValuesResp` 类型
- Produces: 完整因子 tab（定义表 → 已存目录 → cells → 因子值四级下钻）

- [x] **Step 1: `frontend/src/pages/FactorBrowser.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";
import { Input, message, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { api, FactorDir, FactorRow, FactorValuesResp, StoredCell } from "../api";

const PAGE_SIZE = 50;

export default function FactorBrowser() {
  const [q, setQ] = useState("");
  const [fPage, setFPage] = useState(1);
  const [factors, setFactors] = useState<{ total: number; items: FactorRow[] } | null>(null);
  const [fLoading, setFLoading] = useState(false);
  const [selFactor, setSelFactor] = useState<string | null>(null);

  const [dirs, setDirs] = useState<{ total: number; items: FactorDir[] } | null>(null);
  const [dLoading, setDLoading] = useState(false);
  const [dPage, setDPage] = useState(1);
  const [selDir, setSelDir] = useState<FactorDir | null>(null);

  const [selCell, setSelCell] = useState<StoredCell | null>(null);
  const [values, setValues] = useState<FactorValuesResp | null>(null);
  const [vLoading, setVLoading] = useState(false);
  const [vPage, setVPage] = useState(1);
  const [vSize, setVSize] = useState(PAGE_SIZE);

  const loadFactors = useCallback((page: number, qv: string) => {
    setFLoading(true);
    api.factors(qv, page, PAGE_SIZE)
      .then((r) => { setFactors(r); setFPage(page); })
      .catch((e) => message.error(String(e.message)))
      .finally(() => setFLoading(false));
  }, []);
  useEffect(() => { loadFactors(1, q); }, [q, loadFactors]);

  const loadDirs = useCallback((page: number, name: string) => {
    setDLoading(true);
    api.factorDirs(name, page, PAGE_SIZE)
      .then((r) => { setDirs(r); setDPage(page); })
      .catch((e) => message.error(String(e.message)))
      .finally(() => setDLoading(false));
  }, []);

  const loadValues = useCallback((d: FactorDir, cell: StoredCell, page: number, size: number) => {
    setVLoading(true);
    api.factorValues(d.fingerprint, cell.symbol, cell.period, page, size)
      .then((r) => { setValues(r); setVPage(page); setVSize(size); })
      .catch((e) => message.error(String(e.message)))
      .finally(() => setVLoading(false));
  }, []);

  const selectFactor = (name: string) => {
    setSelFactor(name);
    setSelDir(null);
    setSelCell(null);
    setValues(null);
    loadDirs(1, name);
  };

  const selectDir = (d: FactorDir) => {
    setSelDir(d);
    setSelCell(null);
    setValues(null);
  };

  const selectCell = (cell: StoredCell) => {
    setSelCell(cell);
    setValues(null);
    if (selDir) loadValues(selDir, cell, 1, PAGE_SIZE);
  };

  const fCols: ColumnsType<FactorRow> = [
    { title: "名称", dataIndex: "name" },
    { title: "参数", dataIndex: "default_params", render: (v) => JSON.stringify(v) },
    { title: "版本", dataIndex: "version" },
    { title: "类别", dataIndex: "category" },
    { title: "说明/同花顺条件句", dataIndex: "doc", ellipsis: true },
    { title: "已存目录", dataIndex: "stored_dir_count" },
  ];

  const dCols: ColumnsType<FactorDir> = [
    { title: "指纹", dataIndex: "fingerprint", ellipsis: true },
    { title: "参数", dataIndex: "params", render: (v) => JSON.stringify(v) },
    { title: "版本", dataIndex: "version" },
    { title: "复权", dataIndex: "adjust" },
    { title: "组合数", dataIndex: "cells", render: (cells: StoredCell[]) => cells.length },
    { title: "总行数", dataIndex: "total_rows" },
  ];

  const cellCols: ColumnsType<StoredCell> = [
    { title: "标的", dataIndex: "symbol" },
    { title: "周期", dataIndex: "period" },
    { title: "行数", dataIndex: "rows" },
  ];

  const vCols: ColumnsType<[number, number | null]> = [
    { title: "时间", render: (_, r) => dayjs(r[0]).format("YYYY-MM-DD") },
    { title: "值", render: (_, r) => (r[1] === null ? "—" : r[1]) },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Input.Search
        placeholder="搜索因子名/说明"
        allowClear
        onSearch={(v) => setQ(v.trim())}
        style={{ width: 260 }}
      />
      <Table
        rowKey={(r) => r.name}
        size="small"
        loading={fLoading}
        dataSource={factors?.items ?? []}
        columns={fCols}
        rowClassName={(r) => (selFactor === r.name ? "row-selected" : "")}
        onRow={(r) => ({ onClick: () => selectFactor(r.name), style: { cursor: "pointer" } })}
        pagination={{
          current: fPage,
          pageSize: PAGE_SIZE,
          total: factors?.total ?? 0,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 个因子`,
          onChange: (p) => loadFactors(p, q),
        }}
      />
      {selFactor && (
        <>
          <Typography.Title level={5}>{selFactor} · 已存数据目录</Typography.Title>
          <Table
            rowKey={(r) => r.fingerprint}
            size="small"
            loading={dLoading}
            dataSource={dirs?.items ?? []}
            columns={dCols}
            rowClassName={(r) => (selDir?.fingerprint === r.fingerprint ? "row-selected" : "")}
            onRow={(r) => ({ onClick: () => selectDir(r), style: { cursor: "pointer" } })}
            pagination={{
              current: dPage,
              pageSize: PAGE_SIZE,
              total: dirs?.total ?? 0,
              showSizeChanger: false,
              onChange: (p) => loadDirs(p, selFactor),
            }}
          />
        </>
      )}
      {selDir && (
        <>
          <Typography.Title level={5}>组合明细 · {selDir.fingerprint}</Typography.Title>
          <Table
            rowKey={(c) => `${c.symbol}|${c.period}`}
            size="small"
            dataSource={selDir.cells}
            columns={cellCols}
            rowClassName={(c) =>
              selCell?.symbol === c.symbol && selCell?.period === c.period ? "row-selected" : ""
            }
            onRow={(c) => ({ onClick: () => selectCell(c), style: { cursor: "pointer" } })}
          />
        </>
      )}
      {selCell && (
        <>
          <Typography.Title level={5}>
            因子值 · {selDir!.name} {JSON.stringify(selDir!.params)} · {selCell.symbol} {selCell.period}
          </Typography.Title>
          <Table
            rowKey={(r) => String(r[0])}
            size="small"
            loading={vLoading}
            dataSource={values?.rows ?? []}
            columns={vCols}
            pagination={{
              current: vPage,
              pageSize: vSize,
              total: values?.total ?? 0,
              showSizeChanger: true,
              pageSizeOptions: [20, 50, 100, 200],
              showTotal: (t) => `共 ${t} 条`,
              onChange: (p, ps) => { if (selDir && selCell) loadValues(selDir, selCell, p, ps); },
            }}
          />
        </>
      )}
    </Space>
  );
}
```

- [x] **Step 2: 验证** → `cd frontend && npm run build`（无 TS 报错）；浏览器冒烟：
  - 因子 tab 显示 11 个内置因子；搜索 `ma` 过滤正确
  - 点 `ma` → 已存目录表出现（含 `stored_dir_count` 的行）；点某指纹 → cells 表
  - 点某 cell → 因子值分页表

- [ ] **Step 3: Commit**（不执行，保持未勾）

---

## Task 8: 集成冒烟 + 收尾（README/HELP.md + 全量回归 + checkbox 入库）

**Files:**
- Modify: `README.md`（补 Web 查询一节：启动方式、两 tab 功能）
- Modify: `HELP.md`（§3 测试数、§5 代码结构加 `webui`、§9 命令速查加 serve/build）
- Test: 全量回归

- [x] **Step 1: 生产构建 + 单进程冒烟** →
  1. `cd frontend && npm run build`
  2. `uv run python scripts/serve.py`
  3. 浏览器 `http://localhost:8666`：两 tab、分页、搜索、下钻、K 线图全部可用（此时 FastAPI 直接服务 `frontend/dist`，验证 `app.py` 的静态挂载）
  4. `Ctrl-C` 停止

- [x] **Step 2: README 补充** —— 新增"本地 Web 查询界面"一节：
  - 启动：`uv run python scripts/serve.py`（后端 8666，需先 `npm run build` 才有页面；开发可 `npm run dev` 经 proxy）
  - 功能：行情 tab（覆盖索引 → 下钻 K 线 + 图）、因子 tab（定义 → 已存目录 → 因子值）
  - 只读离线、无需 API key

- [x] **Step 3: HELP.md 更新** —— 强制规则（每次改动后同步）：
  - §3 技术栈表：测试数 149 → 当前实际数（跑完 Step 4 后填）；加 `fastapi`/`uvicorn`/前端 Node 工具链
  - §5 代码结构：加 `src/webui/`（app.py/api.py）与 `frontend/`
  - §9 命令速查：加 `uv run python scripts/serve.py` 与 `cd frontend && npm run build`

- [x] **Step 4: 全量回归** → `.venv/bin/python -m pytest tests/`，预期全绿（既有 ~149 + webui/数据层新增用例）

- [x] **Step 5: 计划 checkbox 入库** —— 本计划已勾选步骤随实现入库；Commit 步骤保持未勾

- [ ] **Step 6: Commit**（不执行，保持未勾）

---

## 关键复用

- 惰性/只读存储先例：`src/datacenter/resolver.py`、`src/datacenter/store/klines.py`、`src/factors/store.py`
- parquet 行数快速统计：`pyarrow.parquet.read_metadata(path).num_rows`
- 测试基建：`tests/conftest.py` 的 `make_kline_df`；`tests/test_kline_store.py` / `tests/test_meta.py` / `tests/test_factor_store.py` 既有 fixtures
- 周期常量：`datacenter.constants.ALL_PERIODS`
- 前端 antd 服务端分页模式：`Table` `pagination={{total, current, pageSize, onChange}}`
- 计划/规格：spec `docs/superpowers/specs/2026-08-30-webui-design.md`
