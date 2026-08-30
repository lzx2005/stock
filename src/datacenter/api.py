import time
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
                 rate_per_sec: float = 10.0, max_retries: int = 3):
        data_dir = Path(data_dir)
        self.meta = MetaStore(data_dir / "meta.db")
        self.klines = KlineStore(data_dir / "klines")
        self.client = TickFlowClient(tf=client_tf, rate_per_sec=rate_per_sec,
                                     max_retries=max_retries)
        self.resolver = CacheResolver(self.meta, self.klines, self.client)

    def get_klines(self, symbol: str, period: str = "1d",
                   start_ms: int | None = None, end_ms: int | None = None) -> pd.DataFrame:
        if period not in ALL_PERIODS:
            raise ValueError(f"unknown period {period!r}, expected one of {ALL_PERIODS}")
        end_ms = end_ms if end_ms is not None else int(time.time() * 1000)
        start_ms = start_ms if start_ms is not None else end_ms - THREE_YEARS_MS
        self.resolver.ensure(symbol, period, start_ms, end_ms)
        return self.klines.read([symbol], period, start_ms, end_ms)

    def list_symbols(self, universe: str = "CN_Equity_A") -> list[str]:
        if self.meta.symbol_count() == 0:
            self.meta.upsert_symbols(self.client.list_universe_symbols(universe))
        return self.meta.all_symbols()
