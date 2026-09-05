import logging
import random
import time

import pandas as pd
from tickflow import TickFlow

from datacenter.constants import MAX_PAGE
from datacenter.exceptions import RateLimitError, TickFlowError
from datacenter.client.ratelimit import TokenBucket

log = logging.getLogger(__name__)

KLINE_COLUMNS = ["symbol", "timestamp", "open", "high", "low", "close", "volume", "amount"]


def classify_error(exc: Exception) -> str:
    """返回 rate_limit / client / server。优先按 SDK 异常类判断（实测确认），字符串兜底。
    注意 SDK 的 PermissionError/ConnectionError/TimeoutError 遮蔽内置同名类，必须模块前缀导入。"""
    try:
        from tickflow import _exceptions as tfe
        if isinstance(exc, tfe.RateLimitError):
            return "rate_limit"
        if isinstance(exc, (tfe.BadRequestError, tfe.NotFoundError, tfe.PermissionError,
                            tfe.AuthenticationError)):
            return "client"
        if isinstance(exc, (tfe.InternalServerError, tfe.ConnectionError, tfe.TimeoutError)):
            return "server"
    except ImportError:
        pass
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "too many" in msg:
        return "rate_limit"
    if "invalid" in msg or "not found" in msg or "400" in msg or "404" in msg:
        return "client"
    return "server"


def empty_klines() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in {
        "symbol": "object", "timestamp": "int64", "open": "float64", "high": "float64",
        "low": "float64", "close": "float64", "volume": "int64", "amount": "float64",
    }.items()})


class TickFlowClient:
    """官方 SDK 薄封装：限速 + 重试 + K线分页/批量。只负责"取数"，不管缓存。"""

    def __init__(self, tf: TickFlow | None = None, rate_per_sec: float = 10.0,
                 max_retries: int = 3, sleep=time.sleep):
        self._tf = tf or TickFlow()
        self._bucket = TokenBucket(rate_per_sec)
        self._max_retries = max_retries
        self._sleep = sleep

    def _call(self, fn, *args, **kwargs):
        last_exc = None
        for attempt in range(self._max_retries + 1):
            self._bucket.acquire()
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                kind = classify_error(exc)
                if kind == "client" or attempt == self._max_retries:
                    break
                backoff = (2 ** attempt) * (2.0 if kind == "rate_limit" else 0.5)
                self._sleep(backoff + random.uniform(0, 0.3))
        if classify_error(last_exc) == "rate_limit":
            raise RateLimitError(str(last_exc)) from last_exc
        raise TickFlowError(str(last_exc)) from last_exc

    def get_klines_range(self, symbol: str, period: str,
                         start_ms: int, end_ms: int, adjust: str = "none") -> pd.DataFrame:
        """分页拉取 [start_ms, end_ms] 的 K 线，返回标准列 DataFrame。
        adjust 默认 none（缓存存原始价）；additive 型调用方传原样值穿透回源。

        反向分页：服务端对 [start_time, end_time] 最多返回 5000 根（窗口内最近 5000 根，
        前向分页首页即撞 end_ms 触发 break，拿不到更早数据），故从 end_ms 逐页向旧翻。"""
        frames, cursor = [], end_ms
        while True:
            df = self._call(self._tf.klines.get, symbol, period=period, count=MAX_PAGE,
                            start_time=start_ms, end_time=cursor,
                            adjust=adjust, as_dataframe=True)
            if df is None or df.empty:
                break
            df = df.copy()
            df["symbol"] = symbol
            frames.append(df)
            min_ts = int(df["timestamp"].min())
            # 终止 = 已翻到请求起点之前；不按页长判断（服务端每页上限可能略低于 MAX_PAGE，
            # 如 5m 只回 ~4980 根，页长未满仍可能有更早数据）
            if min_ts <= start_ms:
                break
            if min_ts > cursor:
                # 进度守卫：服务端忽略 end_time、满页但时间戳不向旧翻——断路防死循环
                log.warning("pagination no progress: symbol=%s period=%s cursor=%d min_ts=%d, stop",
                            symbol, period, cursor, min_ts)
                break
            cursor = min_ts - 1
        if not frames:
            return empty_klines()
        out = pd.concat(frames, ignore_index=True)
        out = out.drop_duplicates(subset=["symbol", "timestamp"]).sort_values("timestamp")
        for col in KLINE_COLUMNS:
            if col not in out.columns:
                out[col] = pd.NA
        return out[KLINE_COLUMNS].reset_index(drop=True)

    def list_universe_symbols(self, universe_id: str) -> list[str]:
        uni = self._call(self._tf.universes.get, universe_id)
        return list(uni["symbols"] if isinstance(uni, dict) else uni)

    def get_instruments(self, symbols: list[str]) -> list[dict]:
        """tf.instruments.batch(symbols) -> list[dict]，含 symbol/name/exchange/code 等。"""
        return self._call(self._tf.instruments.batch, symbols)

    def get_financials(self, table: str, symbols: list[str],
                       latest: bool = False) -> pd.DataFrame:
        """统一封装 5 张财务表（income/balance_sheet/cash_flow/metrics/shares）。
        返回 as_dataframe=True 的 DataFrame（含 symbol/period_end 列）。"""
        fn = getattr(self._tf.financials, table)
        return self._call(fn, symbols, latest=latest, as_dataframe=True)

    def get_ex_factors(self, symbol: str) -> list[tuple[int, float]]:
        """返回 [(除权日ms, ex_factor), ...] 按时间升序。
        SDK 实测形态：tf.klines.ex_factors(symbol) -> {symbol: [{timestamp, ex_factor}]}。"""
        data = self._call(self._tf.klines.ex_factors, symbol)
        if isinstance(data, dict):
            rows = data.get(symbol) or data.get("data") or []
        else:
            rows = data or []
        return sorted((int(r["timestamp"]), float(r["ex_factor"])) for r in rows)

    def get_intraday(self, symbol: str, period: str = "1m") -> pd.DataFrame:
        """当日分钟 K（盘中半可变层回源）。SDK: tf.klines.intraday(symbol, period, as_dataframe=True)。
        输出标准化为 KLINE_COLUMNS（补 symbol 列，缺列置空）。"""
        df = self._call(self._tf.klines.intraday, symbol, period=period, as_dataframe=True)
        if df is None or df.empty:
            return empty_klines()
        df = df.copy()
        df["symbol"] = symbol
        for col in KLINE_COLUMNS:
            if col not in df.columns:
                df[col] = pd.NA
        return df[KLINE_COLUMNS].reset_index(drop=True)

    def get_klines_batch_range(self, symbols: list[str], period: str,
                               start_ms: int, end_ms: int) -> pd.DataFrame:
        """批量拉取（回填主力路径）。底层 tf.klines.batch 一次最多 100/200 标的、
        每标的最多 MAX_PAGE 条；满页的标的反向续拉（end_time = 该页最旧时间戳 - 1）。
        返回合并后的标准列 DataFrame。"""
        frames: list[pd.DataFrame] = []
        pending = {s: end_ms for s in symbols}  # cursor = 反向分页的窗口上界
        while pending:
            by_cursor: dict[int, list[str]] = {}
            for s, c in pending.items():
                by_cursor.setdefault(c, []).append(s)
            pending = {}
            for cursor, group in by_cursor.items():
                res = self._call(self._tf.klines.batch, group, period=period,
                                 count=MAX_PAGE, start_time=start_ms, end_time=cursor,
                                 adjust="none", as_dataframe=True)
                res = res or {}
                for sym in group:
                    df = res.get(sym)
                    if df is None or df.empty:
                        continue
                    df = df.copy()
                    df["symbol"] = sym
                    frames.append(df)
                    min_ts = int(df["timestamp"].min())
                    # 终止 = 已翻到请求起点之前；不按页长判断（服务端每页上限可能略低于 MAX_PAGE）
                    if min_ts > start_ms:
                        if min_ts > cursor:
                            # 进度守卫：满页但时间戳不向旧翻（服务端忽略 end_time）——放弃续拉防死循环
                            log.warning("batch pagination no progress: symbol=%s period=%s "
                                        "cursor=%d min_ts=%d, stop", sym, period, cursor, min_ts)
                        else:
                            pending[sym] = min_ts - 1
        if not frames:
            return empty_klines()
        out = pd.concat(frames, ignore_index=True)
        out = out.drop_duplicates(subset=["symbol", "timestamp"]).sort_values(
            ["symbol", "timestamp"])
        for col in KLINE_COLUMNS:
            if col not in out.columns:
                out[col] = pd.NA
        return out[KLINE_COLUMNS].reset_index(drop=True)
