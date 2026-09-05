import time
from pathlib import Path
from typing import Callable

import pandas as pd

from datacenter.adjust import apply_adjust
from datacenter.client.tickflow_client import TickFlowClient
from datacenter.constants import ALL_PERIODS, MINUTE_PERIODS
from datacenter.intraday import IntradayCache
from datacenter.resolver import CacheResolver
from datacenter.store.financials import FinancialStore
from datacenter.store.klines import KlineStore
from datacenter.store.meta import MetaStore
from datacenter.store.realtime import RealtimeStore

THREE_YEARS_MS = 3 * 365 * 86_400_000
METADATA_TTL_SEC = 24 * 3600  # 标的元数据 / 标的池 24h 刷新
SH_OFFSET_MS = 8 * 3600_000  # Asia/Shanghai 与 UTC 的时差


class DataCenter:
    """门面：回测引擎的唯一入口。本地优先，缺失回源，查到即存。"""

    def __init__(self, data_dir: str | Path = "data", client_tf=None,
                 rate_per_sec: float = 10.0, max_retries: int = 3,
                 now_ms: Callable[[], int] | None = None):
        data_dir = Path(data_dir)
        self.meta = MetaStore(data_dir / "meta.db")
        self.klines = KlineStore(data_dir / "klines")
        self.realtime = RealtimeStore(data_dir / "realtime")
        self.financials = FinancialStore(data_dir / "meta.db")
        self.client = TickFlowClient(tf=client_tf, rate_per_sec=rate_per_sec,
                                     max_retries=max_retries)
        self.resolver = CacheResolver(self.meta, self.klines, self.client)
        self.intraday = IntradayCache(ttl_sec=60)
        # now_ms 可注入（测试用合成时间戳时不受真实日期影响）
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))

    def get_klines(self, symbol: str, period: str = "1d",
                   start_ms: int | None = None, end_ms: int | None = None,
                   adjust: str = "forward") -> pd.DataFrame:
        if period not in ALL_PERIODS:
            raise ValueError(f"unknown period {period!r}, expected one of {ALL_PERIODS}")
        end_ms = end_ms if end_ms is not None else int(time.time() * 1000)
        start_ms = start_ms if start_ms is not None else end_ms - THREE_YEARS_MS
        if adjust in ("forward_additive", "backward_additive"):
            # 加法复权本地不实现：穿透回源，不读缓存（一次性查询，不回填）
            return self.client.get_klines_range(symbol, period, start_ms, end_ms, adjust=adjust)

        # 当日段判定：end_ms 超过北京今日 0 点 -> 当日部分走 intraday（TTL 缓存，不落盘）
        now = self._now_ms()
        today_start = now - ((now + SH_OFFSET_MS) % 86_400_000)
        if end_ms >= today_start and period in MINUTE_PERIODS | {"1d"}:
            # 历史段只补到昨日——绝不把"当日已解析"记入永久覆盖区间，
            # 否则明日查询会误判今日已缓存（半可变数据必须每日重取）。
            hist_end = min(end_ms, today_start - 1)
            if start_ms <= hist_end:
                self.resolver.ensure(symbol, period, start_ms, hist_end)
            hist = self.klines.read([symbol], period, start_ms, hist_end)
            if period == "1d":
                # intraday 接口只支持分钟周期；日线的"今日 bar"由当日 1m 聚合而来
                intra = self._today_daily_bar(symbol, today_start)
            else:
                intra = self.intraday.get_or_fetch(
                    symbol, period, lambda: self.client.get_intraday(symbol, period))
                intra = intra[intra["timestamp"] >= max(start_ms, today_start)]
            df = pd.concat([hist, intra]).drop_duplicates("timestamp", keep="last")
        else:
            self.resolver.ensure(symbol, period, start_ms, end_ms)
            df = self.klines.read([symbol], period, start_ms, end_ms)
        if adjust != "none" and not df.empty:
            factors = self.resolver.ensure_ex_factors(symbol)
            df = apply_adjust(df, factors, adjust)
        return df

    def _today_daily_bar(self, symbol: str, today_start: int) -> pd.DataFrame:
        """当日日线 bar：由当日 1m intraday 聚合（首 open/最高/最低/末 close/量加总），
        时间戳 = 北京当日 0 点（与日线存储约定一致）。无当日数据（周末/未开盘）返回空。"""
        minutes = self.intraday.get_or_fetch(
            symbol, "1m", lambda: self.client.get_intraday(symbol, "1m"))
        minutes = minutes[minutes["timestamp"] >= today_start]
        if minutes.empty:
            return minutes
        row = {
            "symbol": symbol,
            "timestamp": today_start,
            "open": minutes["open"].iloc[0],
            "high": minutes["high"].max(),
            "low": minutes["low"].min(),
            "close": minutes["close"].iloc[-1],
            "volume": minutes["volume"].sum(),
        }
        if "amount" in minutes.columns:
            row["amount"] = minutes["amount"].sum()
        return pd.DataFrame([row])

    def list_symbols(self, universe: str = "CN_Equity_A") -> list[str]:
        self.get_universe_symbols(universe)
        return self.meta.all_symbols()

    def get_universe_symbols(self, universe_id: str = "CN_Equity_A") -> list[str]:
        """标的池成员：本地缺失或超 24h 才回源；入库 instruments + universe_members。"""
        key = f"universe:{universe_id}"
        ts = self.meta.get_meta_ts(key)
        if ts is None or time.time() - ts > METADATA_TTL_SEC:
            symbols = self.client.list_universe_symbols(universe_id)
            self.meta.upsert_symbols(symbols)
            self.meta.add_universe_members(universe_id, symbols)
            self.meta.set_meta_flag(key)
        return self.meta.get_universe_symbols(universe_id)

    def get_instruments(self, symbols) -> dict[str, dict]:
        """标的元数据：单个 symbol 缺失或超 24h 才回源；返回 {symbol: {...}}。"""
        if isinstance(symbols, str):
            symbols = [symbols]
        need = [s for s in symbols
                if not self._metadata_fresh(f"inst:{s}")]
        if need:
            rows = self.client.get_instruments(need)
            self.meta.upsert_instruments(rows)
            for s in need:
                self.meta.set_meta_flag(f"inst:{s}")
        return {s: d for s in symbols
                if (d := self.meta.get_instrument(s)) is not None}

    def _metadata_fresh(self, key: str) -> bool:
        ts = self.meta.get_meta_ts(key)
        return ts is not None and (time.time() - ts) <= METADATA_TTL_SEC

    def get_financials(self, table: str, symbols, latest: bool = False) -> pd.DataFrame:
        """财务数据：本地优先，缺失/过期回源，查到即存。
        latest=True 只返回每标的最近一期（受 fin_fetch_log TTL 24h 控制刷新频率）。"""
        if isinstance(symbols, str):
            symbols = [symbols]
        need = [s for s in symbols if self.financials.needs_fetch(s, table, latest)]
        if need:
            # 总是拉全量历史，latest 只在读取端裁剪
            df = self.client.get_financials(table, need, latest=False)
            self.financials.save(table, df)
        return self.financials.load(table, symbols, latest)

    def refresh_financials(self, table: str, symbols) -> None:
        """强制回源刷新（绕过 TTL）。"""
        if isinstance(symbols, str):
            symbols = [symbols]
        df = self.client.get_financials(table, symbols, latest=False)
        self.financials.save(table, df)
