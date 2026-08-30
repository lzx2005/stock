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
                         start_ms: int, end_ms: int) -> pd.DataFrame:
        """分页拉取 [start_ms, end_ms] 的原始价 K 线，返回标准列 DataFrame。"""
        frames, cursor = [], start_ms
        while True:
            df = self._call(self._tf.klines.get, symbol, period=period, count=MAX_PAGE,
                            start_time=cursor, end_time=end_ms,
                            adjust="none", as_dataframe=True)
            if df is None or df.empty:
                break
            df = df.copy()
            df["symbol"] = symbol
            frames.append(df)
            last_ts = int(df["timestamp"].max())
            if len(df) < MAX_PAGE or last_ts >= end_ms:
                break
            if last_ts < cursor:
                # 进度守卫：服务端忽略 start_time、满页但时间戳不前进——断路防死循环
                log.warning("pagination no progress: symbol=%s period=%s cursor=%d last_ts=%d, stop",
                            symbol, period, cursor, last_ts)
                break
            cursor = last_ts + 1
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

    def get_klines_batch_range(self, symbols: list[str], period: str,
                               start_ms: int, end_ms: int) -> pd.DataFrame:
        """批量拉取（回填主力路径）。底层 tf.klines.batch 一次最多 100/200 标的、
        每标的最多 MAX_PAGE 条；满页的标的从各自 last_ts+1 续拉，直到全部不足页。
        返回合并后的标准列 DataFrame。"""
        frames: list[pd.DataFrame] = []
        pending = {s: start_ms for s in symbols}
        while pending:
            by_cursor: dict[int, list[str]] = {}
            for s, c in pending.items():
                by_cursor.setdefault(c, []).append(s)
            pending = {}
            for cursor, group in by_cursor.items():
                res = self._call(self._tf.klines.batch, group, period=period,
                                 count=MAX_PAGE, start_time=cursor, end_time=end_ms,
                                 adjust="none", as_dataframe=True)
                res = res or {}
                for sym in group:
                    df = res.get(sym)
                    if df is None or df.empty:
                        continue
                    df = df.copy()
                    df["symbol"] = sym
                    frames.append(df)
                    last_ts = int(df["timestamp"].max())
                    if len(df) >= MAX_PAGE and last_ts < end_ms:
                        if last_ts < cursor:
                            # 进度守卫：满页但时间戳不前进（服务端忽略 start_time）——放弃续拉防死循环
                            log.warning("batch pagination no progress: symbol=%s period=%s "
                                        "cursor=%d last_ts=%d, stop", sym, period, cursor, last_ts)
                        else:
                            pending[sym] = last_ts + 1
        if not frames:
            return empty_klines()
        out = pd.concat(frames, ignore_index=True)
        out = out.drop_duplicates(subset=["symbol", "timestamp"]).sort_values(
            ["symbol", "timestamp"])
        for col in KLINE_COLUMNS:
            if col not in out.columns:
                out[col] = pd.NA
        return out[KLINE_COLUMNS].reset_index(drop=True)
