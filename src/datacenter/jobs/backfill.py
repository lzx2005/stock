import logging
import time

from datacenter.api import DataCenter
from datacenter.constants import (BACKFILL_ORDER, DAILY_HISTORY_DAYS,
                                  MINUTE_HISTORY_DAYS, MINUTE_PERIODS)

log = logging.getLogger(__name__)


def backfill(dc: DataCenter, periods: list[str] | None = None,
             start_ms: int | None = None, end_ms: int | None = None,
             batch_size: int | None = None, symbols: list[str] | None = None) -> dict:
    """历史回填。断点续传：已标记 done 的 (symbol, period) 跳过。

    分钟周期默认只拉最近 365 天（套餐硬限制），日线级默认 3 年。
    batch_size 默认按周期取套餐上限（分钟 100 / 日线 200）。
    symbols 默认全市场（CN_Equity_A）；可传子集（如分钟抽样）。
    """
    end_ms = end_ms if end_ms is not None else int(time.time() * 1000)
    symbols = symbols if symbols is not None else dc.list_symbols()
    report = {"done": [], "failed": {}}

    for period in (periods or BACKFILL_ORDER):
        default_days = MINUTE_HISTORY_DAYS if period in MINUTE_PERIODS else DAILY_HISTORY_DAYS
        p_start = start_ms if start_ms is not None else end_ms - default_days * 86_400_000
        size = batch_size or (100 if period in MINUTE_PERIODS else 200)
        todo = dc.meta.pending_symbols(symbols, period)
        log.info("period=%s pending=%d", period, len(todo))
        for i in range(0, len(todo), size):
            batch = todo[i:i + size]
            try:
                df = dc.client.get_klines_batch_range(batch, period, p_start, end_ms)
            except Exception as exc:
                for s in batch:
                    report["failed"][s] = str(exc)
                log.warning("batch failed: period=%s [%d:%d]: %s", period, i, i + size, exc)
                continue
            dc.klines.write(df, period, tag="backfill")
            for s in batch:
                # 空数据同样是"已解析"，标记覆盖防打空
                dc.meta.extend_coverage(s, period, p_start, end_ms)
                dc.meta.mark_done(s, period)
                report["done"].append(s)
            log.info("period=%s batch %d-%d done", period, i, i + len(batch))
    return report
