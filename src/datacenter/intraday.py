"""盘中半可变层：当日数据 TTL 缓存。

收盘前的当日数据是"半可变"的（分钟 K 会随实时撮合滚动），不适合按永久覆盖
区间缓存。盘中查询当日段直接回源 intraday 接口，仅用 TTL 内存缓存避免重复打接口；
收盘后由日终任务固化进 KlineStore 永久覆盖区间。
"""

import time

import pandas as pd


class IntradayCache:
    """盘中当日数据 TTL 缓存（纯内存，不落盘——收盘后由日终任务固化）。"""

    def __init__(self, ttl_sec=60, now=time.monotonic):
        self._ttl, self._now = ttl_sec, now
        self._cache: dict[tuple[str, str], tuple[float, pd.DataFrame]] = {}

    def get_or_fetch(self, symbol, period, fetch):
        """TTL 内命中直接返回缓存；否则调用 fetch() 取新数据并缓存。"""
        key = (symbol, period)
        hit = self._cache.get(key)
        if hit and self._now() - hit[0] < self._ttl:
            return hit[1]
        df = fetch()
        self._cache[key] = (self._now(), df)
        return df
