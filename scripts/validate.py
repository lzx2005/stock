"""数据质量校验 CLI：抽样比对 + 1m/1d 交叉校验，报告落 job_reports 表。

运行（项目根目录，需 TICKFLOW_API_KEY）:
    source ~/.zshrc && .venv/bin/python scripts/validate.py [--symbols 55] [--days 60]

- 从标的池随机抽 --symbols 只（默认 1%），对近 --days 天做 sample_compare（回源 vs 本地）
- 对最新交易日跑 cross_check_minute_daily（1m 聚合 vs 1d，需分钟K权限，无权限自动跳过）
"""
import argparse
import random
import time

from datacenter import DataCenter
from datacenter.quality import cross_check_minute_daily, sample_compare

DAY_MS = 86_400_000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=0,
                    help="抽样数量，0=取标的池百分之一")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    dc = DataCenter(data_dir=args.data_dir, rate_per_sec=100)
    universe = dc.list_symbols()
    n = args.symbols or max(1, len(universe) // 100)
    sample = random.sample(universe, min(n, len(universe)))

    end = int(time.time() * 1000)
    start = end - args.days * DAY_MS

    print(f"== 抽样比对：{len(sample)}/{len(universe)} 只，近 {args.days} 天 ==")
    bad = sample_compare(dc, sample, "1d", start, end)
    print(f"不一致：{len(bad)} 只 {bad}")
    dc.meta.save_job_report("sample_compare", {"status": "ok" if not bad else "bad",
                                               "n_bad": len(bad), "detail": ",".join(bad)})

    print("\n== 1m/1d 交叉校验（最新交易日） ==")
    cal = sorted(dc.get_klines("000001.SH", "1d", start, end, adjust="none")["timestamp"])
    if not cal:
        print("无交易日历数据，跳过")
        return
    date = cal[-1]
    xbad, skipped = [], 0
    for s in sample:
        try:
            r = cross_check_minute_daily(dc, s, date)
        except Exception as e:  # 无分钟K权限等：记录后跳过
            print(f"  跳过 {s}: {e}")
            break
        if r is None:
            skipped += 1
        elif r:
            xbad.append(s)
    print(f"不一致：{len(xbad)} 只 {xbad}；无分钟数据跳过 {skipped} 只")
    dc.meta.save_job_report("cross_check", {"status": "ok" if not xbad else "bad",
                                            "n_bad": len(xbad), "detail": ",".join(xbad)})


if __name__ == "__main__":
    main()
