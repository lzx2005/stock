"""WS 行情消息缓冲器（Collector）+ 采集连接层（run_collector）。

Collector 与传输解耦：WS 连接层只负责把收到的消息转成 dict 喂给 `on_message`，
本类负责字段校验、缓冲与批量落盘。

落盘策略（任一触发）：
- 缓冲满 `flush_count` 条（on_message 内立即 flush）
- 距上次落盘超过 `flush_interval` 秒（外部循环定期调 `maybe_flush()`）
"""

import asyncio
import logging
import time

import pandas as pd

logger = logging.getLogger(__name__)

_REQUIRED = ("symbol", "ts_ms", "last_price")


class Collector:
    """WS 消息缓冲器：满 flush_count 条或距上次落盘超 flush_interval 秒即批量写盘。"""

    def __init__(self, store, flush_interval=5.0, flush_count=1000, now=time.monotonic):
        self.store = store
        self.flush_interval = flush_interval
        self.flush_count = flush_count
        self._now = now
        self._buf: list[dict] = []
        self.last_flush = 0.0  # 从 0 起步，首次 maybe_flush 即可落盘

    def on_message(self, msg: dict) -> None:
        """接收一条消息：校验必需字段，缺则记日志丢弃；满 flush_count 立即 flush。"""
        if not isinstance(msg, dict):
            logger.warning("drop non-dict message: %r", msg)
            return
        if any(msg.get(k) is None for k in _REQUIRED):
            logger.warning("drop malformed message (missing %s): %r",
                           "/".join(k for k in _REQUIRED if msg.get(k) is None), msg)
            return
        self._buf.append({
            "symbol": msg["symbol"],
            "ts_ms": msg["ts_ms"],
            "last_price": msg["last_price"],
            "volume": msg.get("volume", 0),
            "turnover": msg.get("turnover", 0.0),
            "kind": msg.get("kind", "snapshot"),
        })
        if len(self._buf) >= self.flush_count:
            self.flush()

    def maybe_flush(self, now=None) -> None:
        """缓冲非空且距上次落盘超间隔时落盘。`now` 由调用方注入（测试用）。"""
        now = now if now is not None else self._now()
        if self._buf and now - self.last_flush >= self.flush_interval:
            self.flush()

    def flush(self) -> None:
        """立即把缓冲批量写盘并清空。"""
        if not self._buf:
            return
        df = pd.DataFrame(self._buf)
        written = self.store.write(df)
        self._buf = []
        self.last_flush = self._now()
        if written:
            logger.info("flushed %d rows -> %d files", len(df), len(written))


def _normalize_quote(q: dict) -> dict:
    """SDK quotes 消息单条 → Collector 需要的字段（缺失交由 Collector 校验丢弃）。

    quote dict 的实际字段名在探测时因无 WS 权限不可观测，按 SDK 惯例兼容
    `ts_ms`/`timestamp` 两种时间戳键名，量类键缺失时给默认值。
    """
    ts_ms = q.get("ts_ms")
    if ts_ms is None:
        ts_ms = q.get("timestamp")
    return {
        "symbol": q.get("symbol"),
        "ts_ms": ts_ms,
        "last_price": q.get("last_price"),
        "volume": q.get("volume", 0),
        "turnover": q.get("turnover", q.get("amount", 0.0)),
        "kind": "snapshot",
    }


async def _periodic_flush(collector: Collector, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        collector.maybe_flush()


async def run_collector(symbols, store, reconnect_max=10, flush_interval=5.0, flush_count=1000):
    """启动 WS 实时采集：SDK 流 → Collector → RealtimeStore。

    - SDK（AsyncMarketStream）内部已处理 3s 重连 + 重连后自动重订阅；
    - 外层对 SDK 无法恢复的退出（如 403 无权限、connect 抛错）按指数退避重试
      reconnect_max 次（1s,2s,4s...封顶 60s）；
    - 后台定时调 maybe_flush；退出前 flush 清空缓冲。
    """
    from tickflow import AsyncTickFlow

    collector = Collector(store, flush_interval=flush_interval, flush_count=flush_count)

    async with AsyncTickFlow() as client:
        stream = client.stream

        def _on_quotes(quotes):
            for q in quotes:
                collector.on_message(_normalize_quote(q))

        def _on_error(msg):
            logger.error("stream error: %s", msg)

        stream.on_quotes(_on_quotes)
        stream.on_error(_on_error)

        flush_task = asyncio.create_task(_periodic_flush(collector, flush_interval))
        try:
            await stream.subscribe("quotes", list(symbols))
            delay = 1.0
            for attempt in range(1, reconnect_max + 1):
                try:
                    await stream.connect()  # 阻塞；可恢复错误在 SDK 内重连，返回 = 不可恢复退出
                    logger.warning("stream closed (attempt %d), reconnecting in %.0fs", attempt, delay)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 - 重连循环兜底
                    logger.error("connect failed: %s", e)
                if attempt < reconnect_max:
                    await asyncio.sleep(delay)
                    await stream.subscribe("quotes", list(symbols))
                    delay = min(delay * 2, 60.0)
        finally:
            flush_task.cancel()
            collector.flush()
            await stream.close()
