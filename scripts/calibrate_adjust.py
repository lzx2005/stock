"""校准 ex_factor 语义：本地公式 vs 服务端 forward 复权对拍。

运行（项目根目录，需 TICKFLOW_API_KEY）:
    source ~/.zshrc && .venv/bin/python scripts/calibrate_adjust.py

结论写入 docs/sdk-notes.md。决定 adjust.py 的乘/除方向与累积规则。
"""
import numpy as np
import pandas as pd
from tickflow import TickFlow

tf = TickFlow()
raw = tf.klines.get("600000.SH", period="1d", count=800, adjust="none", as_dataframe=True)
fwd = tf.klines.get("600000.SH", period="1d", count=800, adjust="forward", as_dataframe=True)
data = tf.klines.ex_factors("600000.SH")
factors = sorted((int(r["timestamp"]), float(r["ex_factor"])) for r in data["600000.SH"])

merged = raw[["timestamp", "close"]].merge(
    fwd[["timestamp", "close"]], on="timestamp", suffixes=("_raw", "_fwd"))
merged["ratio"] = merged["close_fwd"] / merged["close_raw"]
merged["date"] = pd.to_datetime(merged["timestamp"], unit="ms").dt.strftime("%Y-%m-%d")

print(f"=== 600000.SH: {len(merged)} 根日线, {len(factors)} 个除权因子 ===")
print(f"采样范围内除权日: {[pd.to_datetime(d, unit='ms').strftime('%Y-%m-%d') for d, _ in factors if d > merged['timestamp'].min()]}")

print("\n=== 最近 15 个交易日 ratio (close_fwd/close_raw) ===")
print(merged[["date", "close_raw", "close_fwd", "ratio"]].tail(15).to_string(index=False))

# 拟合：predicted_ratio(t) = ∏_{date_i > t} f_i^k，k=+1 或 -1（前复权：最新价不动，历史价缩放）
ts = merged["timestamp"].to_numpy()
best = None
for k in (+1, -1):
    pred = np.ones(len(merged))
    for d, f in factors:
        pred[ts < d] *= f**k
    err = float(np.abs(pred - merged["ratio"]).max())
    print(f"k={k:+d}（ratio = ∏ f^{{{k:+d}}}，除权日之后 bar 才缩放）: 最大误差 {err:.6f}")
    if best is None or err < best[0]:
        best = (err, k)

# 另一种可能：除权日当日及之后缩放
for k in (+1, -1):
    pred = np.ones(len(merged))
    for d, f in factors:
        pred[ts <= d] *= f**k
    err = float(np.abs(pred - merged["ratio"]).max())
    print(f"k={k:+d}（含当日，<=）: 最大误差 {err:.6f}")
    if err < best[0]:
        best = (err, k)

err, k = best
print(f"\n最佳拟合: k={k:+d}, 最大误差 {err:.6f}")
