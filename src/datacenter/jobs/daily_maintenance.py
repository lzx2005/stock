"""日终维护任务（spec §7.2）：收盘后跑一次。

四步：拉当日全市场 K 线固化（可多周期，默认 日K+1m）→ WS/REST 核对 → 更新除权因子 →
刷新 instruments/标的池（超 TTL 的）→ 更新 coverage。
幂等：last-wins 去重 + coverage 并集，重复跑不产生重复数据。产出报告入 job_reports 表。
"""

import time

import pandas as pd

from datacenter.api import METADATA_TTL_SEC, DataCenter

DAY_MS = 86_400_000
SH_OFFSET_MS = 8 * 3600_000  # Asia/Shanghai = UTC+8，与 KlineStore 分区口径一致
RECONCILE_TOL = 0.01          # WS 聚合 vs REST 1m 的 close/volume 相对容差


def run_daily_maintenance(dc: DataCenter, today_ms: int | None = None,
                          periods: list[str] | None = None) -> dict:
    today_ms = today_ms or int(time.time() * 1000)
    periods = periods or ["1d", "1m"]
    # 北京时间当日 0 点的 ms 时间戳（直接用 UTC 取模会有 8 小时边界错误）
    day_start = today_ms - ((today_ms + SH_OFFSET_MS) % DAY_MS)
    symbols = dc.list_symbols()
    updated, failed = 0, {}
    # 各周期按覆盖缺口回源固化当日；空数据也 extend coverage（防打空）
    for period in periods:
        for s in symbols:
            cov = dc.meta.get_coverage(s, period)
            start = (cov[1] + 1) if cov else day_start
            if start > today_ms:  # 已是最新，跳过
                continue
            try:
                df = dc.client.get_klines_range(s, period, start, today_ms)
                if not df.empty:
                    dc.klines.write(df, period, tag="daily")
                    updated += 1
                dc.meta.extend_coverage(s, period, start, today_ms)
            except Exception as exc:
                failed[s] = str(exc)
    # WS 当日快照 vs REST 1m 核对（REST 已固化入库，以其为准；WS 数据留在 realtime/ 不动）
    mismatches = reconcile_ws_rest(dc, symbols, day_start, today_ms)
    factors_checked = refresh_ex_factors(dc, symbols)
    refresh_metadata(dc)
    report = {"symbols_updated": updated, "failed": failed,
              "ex_factors_checked": factors_checked,
              "reconcile_mismatches": mismatches}
    dc.meta.save_job_report("daily", report)
    return report


def aggregate_snapshots(snaps: pd.DataFrame, minute_ms: int = 60_000) -> pd.DataFrame:
    """当日快照按分钟窗口聚合：首条 last_price=open、末条=close、max/min=high/low、
    volume 取窗口差分（快照 volume 为当日累计，差分化得到窗口成交量）。
    返回列：ts(窗口起点), open, close, high, low, volume。"""
    if snaps.empty:
        return snaps[[]]
    df = snaps.sort_values("ts_ms").copy()
    buckets = df["ts_ms"] // minute_ms
    df["bucket"] = buckets
    df["bucket_ts"] = buckets * minute_ms
    agg = df.groupby("bucket").agg(
        ts=("bucket_ts", "first"),
        open=("last_price", "first"),
        close=("last_price", "last"),
        high=("last_price", "max"),
        low=("last_price", "min"),
        vol_max=("volume", "max"),
    ).reset_index(drop=True)
    agg["volume"] = agg["vol_max"].diff().fillna(agg["vol_max"]).astype("int64")
    return agg[["ts", "open", "close", "high", "low", "volume"]]


def reconcile_ws_rest(dc: DataCenter, symbols: list[str],
                      day_start: int, today_ms: int) -> list[dict]:
    """realtime/ 当日快照聚合的 1m 与 klines/ 的 REST 1m 逐分钟对比 close/volume。
    容差 1%，差异列表返回（进 job_reports）；不一致以 REST 为准。"""
    mismatches: list[dict] = []
    for s in symbols:
        snaps = dc.realtime.read(s, day_start, today_ms)
        if snaps.empty:
            continue
        rest = dc.klines.read([s], "1m", day_start, today_ms)
        if rest.empty:
            continue  # REST 未固化当日，无法核对
        agg = aggregate_snapshots(snaps)
        rest_by_ts = rest.set_index("timestamp")
        for _, row in agg.iterrows():
            if row["ts"] not in rest_by_ts.index:
                continue
            m = rest_by_ts.loc[row["ts"]]
            close_diff = abs(row["close"] - m["close"]) / m["close"] if m["close"] else 0.0
            vol_diff = abs(row["volume"] - m["volume"]) / m["volume"] if m["volume"] else 0.0
            if close_diff > RECONCILE_TOL or vol_diff > RECONCILE_TOL:
                mismatches.append({
                    "symbol": s, "ts": int(row["ts"]),
                    "ws_close": float(row["close"]), "rest_close": float(m["close"]),
                    "ws_volume": int(row["volume"]), "rest_volume": int(m["volume"]),
                })
    return mismatches


def refresh_ex_factors(dc: DataCenter, symbols: list[str]) -> int:
    """逐 symbol 重新回源 ex-factors（upsert 幂等），返回检查过的数量。
    因子历史不可变，但新除权事件会追加，日终必须全量重拉每个 symbol。"""
    for s in symbols:
        factors = dc.client.get_ex_factors(s)
        dc.meta.upsert_ex_factors(s, factors)
        dc.meta.set_meta_flag(f"exf:{s}")
    return len(symbols)


def refresh_metadata(dc: DataCenter) -> None:
    """instruments 与标的池成员：距上次刷新超 24h（meta_kv fetched_at）才回源。
    get_universe_symbols 内部已按 TTL 判断；instruments 明细按需在 get_instruments 刷新。"""
    universe = "CN_Equity_A"
    if dc.meta.get_meta_ts(f"universe:{universe}") is None \
            or time.time() - dc.meta.get_meta_ts(f"universe:{universe}") > METADATA_TTL_SEC:
        dc.get_universe_symbols(universe)
