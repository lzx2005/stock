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

    def ensure_ex_factors(self, symbol: str) -> list[tuple[int, float]]:
        """因子不可变：本地有就直接用；没有则回源一次并永久缓存。
        注意：'没有'可能是真没有（从未除权），用 exf:{symbol} 标记防打空。"""
        if self._meta.get_meta_flag(f"exf:{symbol}"):
            return self._meta.get_ex_factors(symbol)
        factors = self._client.get_ex_factors(symbol)
        self._meta.upsert_ex_factors(symbol, factors)
        self._meta.set_meta_flag(f"exf:{symbol}")
        return factors
