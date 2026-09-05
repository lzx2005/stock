"""因子库批量预热：FactorStore.warm 对指定标的×因子算一遍入库，之后回测直接命中缓存。
运行：source ~/.zshrc && .venv/bin/python scripts/factor_warm.py --symbols 600000.SH,000001.SZ --factors ma,vol_ratio --years 5
"""
import argparse, time
from datacenter import DataCenter
from factors import FactorStore
import factors.factors  # noqa: F401 注册内置因子

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", required=True, help="逗号分隔")
    ap.add_argument("--factors", default="ma,ema,rsi,macd_hist,kdj_j,boll_up,boll_low,vol_ratio,mom,bias")
    ap.add_argument("--period", default="1d")
    ap.add_argument("--years", type=int, default=5)
    a = ap.parse_args()
    end = int(time.time() * 1000)
    start = end - a.years * 365 * 86_400_000
    fs = FactorStore(DataCenter())
    fs.warm(a.symbols.split(","), a.factors.split(","), a.period, start, end, show_progress=True)

if __name__ == "__main__":
    main()
