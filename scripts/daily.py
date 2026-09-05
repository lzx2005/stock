"""日终维护 CLI：收盘后跑一次，拉当日全市场日 K、刷新除权因子与元数据，产出报告。

用法（项目根目录，需 TICKFLOW_API_KEY）:
    source ~/.zshrc && .venv/bin/python scripts/daily.py [--data-dir data] [--rate 100]

cron 示例（每个工作日收盘后）:
    0 16 * * 1-5 cd /path/to/stock && uv run python scripts/daily.py
"""
import argparse

from datacenter import DataCenter
from datacenter.jobs.daily_maintenance import run_daily_maintenance


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--rate", type=float, default=100.0, help="每秒请求上限")
    args = ap.parse_args()

    dc = DataCenter(data_dir=args.data_dir, rate_per_sec=args.rate)
    report = run_daily_maintenance(dc)
    print(report)


if __name__ == "__main__":
    main()
