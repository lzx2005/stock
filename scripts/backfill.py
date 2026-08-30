"""历史回填入口。
用法:
  uv run python scripts/backfill.py                      # 全量：10 周期 × 全市场
  uv run python scripts/backfill.py --periods 1d,1w      # 只补指定周期
  uv run python scripts/backfill.py --rate 0.5           # 分钟批量档
中断后重跑同一命令即可续传。
"""
import argparse
import logging
import time

from datacenter import DataCenter
from datacenter.jobs.backfill import backfill

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--periods", type=str, default=None, help="逗号分隔，默认全部（先粗后细）")
    p.add_argument("--rate", type=float, default=1.0,
                   help="每秒请求上限（日线批量 60次/分=1.0，分钟批量 30次/分=0.5）")
    p.add_argument("--batch-size", type=int, default=None,
                   help="默认按周期取套餐上限（日线 200 / 分钟 100）")
    p.add_argument("--data-dir", type=str, default="data")
    args = p.parse_args()

    dc = DataCenter(data_dir=args.data_dir, rate_per_sec=args.rate)
    periods = args.periods.split(",") if args.periods else None
    t0 = time.time()
    report = backfill(dc, periods=periods, batch_size=args.batch_size)
    print(f"\n耗时 {time.time() - t0:.0f}s | 完成 {len(report['done'])} 个 symbol×period"
          f" | 失败 {len(report['failed'])} 个")
    if report["failed"]:
        print("失败样例:", list(report["failed"].items())[:10])


if __name__ == "__main__":
    main()
