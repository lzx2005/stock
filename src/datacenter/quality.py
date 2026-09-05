"""数据质量：交易日历、日线连续性检查、缺口补拉。

coverage 语义是"已解析"而非"有数据"（见 CacheResolver.ensure），缺口在 coverage
之内时 resolver 不会补拉——所以 repair_gaps 必须直接调 client 绕过 coverage。
新股上市前 / 长期停牌造成的"缺口"属正常，find_gaps 只报，由调用方结合上市日期判断。
"""

import pandas as pd

from datacenter.api import DataCenter

DAY_MS = 86_400_000


def trading_calendar(dc: DataCenter, start_ms: int, end_ms: int) -> set[int]:
    """以上证指数（000001.SH）日线为交易日历。"""
    df = dc.get_klines("000001.SH", "1d", start_ms, end_ms, adjust="none")
    return set(df["timestamp"])


def find_gaps(dc: DataCenter, symbol: str, period: str,
              start_ms: int, end_ms: int) -> list[tuple[int, int]]:
    """对照交易日历找日线缺口，按日历索引合并成连续缺口区间（仅 period='1d'）。"""
    if period != "1d":
        raise ValueError("find_gaps 目前只支持 1d")
    cal = sorted(trading_calendar(dc, start_ms, end_ms))
    have = set(dc.get_klines(symbol, "1d", start_ms, end_ms, adjust="none")["timestamp"])
    missing = [t for t in cal if t not in have]
    idx = {t: i for i, t in enumerate(cal)}
    gaps: list[list[int]] = []
    for t in missing:
        if gaps and idx[t] == idx[gaps[-1][1]] + 1:
            gaps[-1][1] = t
        else:
            gaps.append([t, t])
    return [(a, b) for a, b in gaps]


def repair_gaps(dc: DataCenter, symbol: str, gaps: list[tuple[int, int]]) -> None:
    """对每个缺口段强制回源补拉（绕开 coverage），写入本地。"""
    for gs, ge in gaps:
        df = dc.client.get_klines_range(symbol, "1d", gs - DAY_MS, ge + DAY_MS)
        dc.klines.write(df, "1d", tag="repair")


def sample_compare(dc: DataCenter, symbols: list[str], period: str,
                   start_ms: int, end_ms: int, tol: float = 1e-6) -> list[str]:
    """对给定 symbols 重新回源（绕开缓存），与本地逐 (timestamp, close/volume) 比对。
    返回不一致的 symbol 列表。"""
    bad = []
    for s in symbols:
        remote = dc.client.get_klines_range(s, period, start_ms, end_ms)
        local = dc.klines.read([s], period, start_ms, end_ms)
        if remote.empty or local.empty:
            continue
        merged = remote[["timestamp", "close", "volume"]].merge(
            local[["timestamp", "close", "volume"]], on="timestamp", suffixes=("_r", "_l"))
        if merged.empty:
            continue
        if ((merged["close_r"] - merged["close_l"]).abs().max() > tol
                or (merged["volume_r"] - merged["volume_l"]).abs().max() > tol):
            bad.append(s)
    return bad


def cross_check_minute_daily(dc: DataCenter, symbol: str,
                             date_ms: int, tol: float = 0.01) -> list[str] | None:
    """1m 聚合 volume/amount 与当日 1d 行比对（容差 tol 百分比）。
    以该日 1d bar 自身 timestamp 为当日起点。
    返回不一致 symbol 列表；一致返回 []；本地无 1m 数据（无法比对）返回 None。"""
    d = dc.klines.read([symbol], "1d", date_ms - 2 * DAY_MS, date_ms + 2 * DAY_MS)
    if d.empty:
        return None
    day_start = int(d["timestamp"].iloc[0])
    m = dc.klines.read([symbol], "1m", day_start, day_start + DAY_MS - 1)
    if m.empty:
        return None
    agg = {"volume": float(m["volume"].sum()), "amount": float(m["amount"].sum())}
    for col in ("volume", "amount"):
        ref = float(d["volume"].iloc[0] if col == "volume" else d["amount"].iloc[0])
        if ref == 0:
            if agg[col] != ref:
                return [symbol]
        elif abs(agg[col] - ref) / abs(ref) > tol:
            return [symbol]
    return []
