"""WS 实时行情采集进程入口。

用法（项目根目录，需 TICKFLOW_API_KEY）:
    source ~/.zshrc && .venv/bin/python scripts/ws_collect.py [--universe CN_Equity_A]
    source ~/.zshrc && .venv/bin/python scripts/ws_collect.py --symbols 600000.SH,000001.SZ

交易时段运行；SIGINT (Ctrl-C) 优雅退出（退出前 flush 缓冲，落盘不丢已收数据）。
落盘位置：`<data-dir>/realtime/date=<YYYY-MM-DD>/rt-*.parquet`。
"""
import argparse
import asyncio
import logging
from pathlib import Path

from datacenter import DataCenter
from datacenter.jobs.ws_collector import run_collector
from datacenter.store.realtime import RealtimeStore

logger = logging.getLogger(__name__)


def main():
    ap = argparse.ArgumentParser(description="WS 实时行情采集")
    ap.add_argument("--universe", default="CN_Equity_A", help="标的池 ID，--symbols 缺省时用")
    ap.add_argument("--symbols", default=None, help="逗号分隔标的列表，优先于 --universe")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--flush-interval", type=float, default=5.0, help="定时落盘间隔（秒）")
    ap.add_argument("--flush-count", type=int, default=1000, help="缓冲条数阈值")
    ap.add_argument("--reconnect-max", type=int, default=10, help="不可恢复断线后的重连次数")
    args = ap.parse_args()

    logfile = Path(args.data_dir) / "ws_collector.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(logfile)],
    )

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        logger.info("explicit %d symbols", len(symbols))
    else:
        dc = DataCenter(data_dir=args.data_dir)
        symbols = dc.get_universe_symbols(args.universe)
        logger.info("universe %s -> %d symbols", args.universe, len(symbols))

    store = RealtimeStore(Path(args.data_dir) / "realtime")
    asyncio.run(run_collector(
        symbols, store,
        reconnect_max=args.reconnect_max,
        flush_interval=args.flush_interval,
        flush_count=args.flush_count,
    ))
    logger.info("collector exited")


if __name__ == "__main__":
    main()
