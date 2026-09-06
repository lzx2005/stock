"""Web 查询界面 API：默认只读；仅 /klines?refresh=1 会懒构造 DataCenter 回源补最新。"""
import json
import time

import pandas as pd
from fastapi import APIRouter, HTTPException, Request

from datacenter.constants import ALL_PERIODS
import factors.factors  # noqa: F401 —— import 即注册内置因子
from factors.registry import get_factor, list_factors

router = APIRouter(prefix="/api")

KLINE_COLS = ["timestamp", "open", "high", "low", "close", "volume", "amount"]


def _pagination(page: int, size: int) -> tuple[int, int]:
    return max(1, page), min(2000, max(1, size))


def _get_dc(app):
    """懒构造 DataCenter（挂在 app.state.dc 复用）。仅 refresh=1 时调用——
    需要 TICKFLOW_API_KEY；无 key/网络异常由调用方捕获，退回纯缓存。"""
    dc = getattr(app.state, "dc", None)
    if dc is None:
        from datacenter import DataCenter  # 局部 import：保持默认路径离线只读
        dc = DataCenter(data_dir=app.state.data_dir)
        app.state.dc = dc
    return dc


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
           page: int = 1, size: int = 50, refresh: bool = False):
    page, size = _pagination(page, size)
    if period not in ALL_PERIODS:
        raise HTTPException(404, f"unknown period {period!r}")
    st = request.app.state.stores
    refresh_error = None
    if refresh:
        # 回源补最新（缺失段自动回填；当日走 intraday 缓存，不落盘）。
        # 成功则直接用返回的 df 分页——这样当日盘中 bar 也能上屏。
        try:
            # adjust="none"：缓存存的是原始价，与下方只读缓存路径口径一致
            df = _get_dc(request.app).get_klines(
                symbol, period, start_ms, int(time.time() * 1000), adjust="none")
        except Exception as e:
            df, refresh_error = None, str(e)
        if df is not None:
            total = len(df)
            lo = (page - 1) * size
            page_df = df.iloc[lo:lo + size]
            rows = ([list(r) for r in page_df[KLINE_COLS].itertuples(index=False)]
                    if all(c in page_df.columns for c in KLINE_COLS) else [])
            return {"symbol": symbol, "period": period, "total": total,
                    "page": page, "size": size, "refreshed": True,
                    "rows": rows}
    if start_ms is None or end_ms is None:
        cov = st.meta.get_coverage(symbol, period)
        if cov is None:
            return {"symbol": symbol, "period": period, "total": 0,
                    "page": page, "size": size, "refreshed": False,
                    "refresh_error": refresh_error, "rows": []}
        start_ms, end_ms = cov
    try:
        df = st.klines.read([symbol], period, start_ms, end_ms)
        total = st.klines.count([symbol], period, start_ms, end_ms)
    except Exception as e:
        # 存储层异常（如分区布局损坏）不抛 500：返回空结果并在 refresh_error 里带原因，
        # 前端据此提示"本地缓存不可用"，而不是整页报错。
        err = f"本地缓存读取失败：{e}"
        return {"symbol": symbol, "period": period, "total": 0,
                "page": page, "size": size, "refreshed": False,
                "refresh_error": refresh_error or err, "rows": []}
    lo = (page - 1) * size
    page_df = df.iloc[lo:lo + size]
    return {"symbol": symbol, "period": period, "total": total,
            "page": page, "size": size, "refreshed": False,
            "refresh_error": refresh_error,
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
