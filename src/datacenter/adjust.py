"""本地复权计算。

语义经真实对拍校准（最大误差 0，见 docs/sdk-notes.md §9、scripts/calibrate_adjust.py）：
- ex_factor > 1，表示除权日价格回落比例（如 10->5 除权，factor=2.0）
- forward  （前复权）：基准 = 最新价；除权日**之前**的 bar 价格 × (1/factor)，对后续所有因子累积
- backward （后复权）：历史不变；除权日**及之后**的 bar 价格 × factor，累积到该日所有因子
- volume 反向缩放（除以同一价格因子），amount 保持不变（amount ≈ price × volume）
- additive 型复权（加除权差额）本地不实现，抛 ValueError 提示穿透回源
"""

import numpy as np
import pandas as pd

PRICE_COLS = ["open", "high", "low", "close"]

#: 返回的复权类型。SDK 侧另支持 qfq/hfq 等别名，本地只认这三种。
SUPPORTED = ("none", "forward", "backward")


def apply_adjust(df: pd.DataFrame, factors: list[tuple[int, float]],
                 adjust: str = "none") -> pd.DataFrame:
    """对原始价 DataFrame 应用复权，返回新 DataFrame（不改入参）。

    df:      含 timestamp/OHLC/volume 的标准列 DataFrame
    factors: [(除权日ms, ex_factor), ...]，任意顺序（内部排序）
    adjust:  "none" | "forward" | "backward"
    """
    if adjust == "none" or df.empty or not factors:
        return df.copy()
    if adjust not in SUPPORTED:
        raise ValueError(
            f"adjust={adjust!r} 本地不支持（additive 型请穿透回源）")

    out = df.copy()
    ts = out["timestamp"].to_numpy()
    cum = np.ones(len(out), dtype="float64")
    for ex_ts, factor in sorted(factors):
        if factor <= 0:
            raise ValueError(f"ex_factor 必须为正数，收到 {factor!r} @ {ex_ts}")
        if adjust == "forward":
            cum[ts < ex_ts] *= 1.0 / factor
        else:  # backward
            cum[ts >= ex_ts] *= factor
    for col in PRICE_COLS:
        out[col] = out[col].to_numpy() * cum
    out["volume"] = (out["volume"].to_numpy() / cum).round().astype("int64")
    return out
