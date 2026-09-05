"""技术指标库：纯 pandas 向量化，零第三方依赖。

实现语义约定（与 tests/test_indicators.py 的循环参考一致）：
- ema / rsi 平滑用 `ewm(adjust=False)`，第一个有效值作种子后递归
- rsi 用 Wilder 平滑（alpha=1/n）
- kdj 用 com=2 递归（等价于 2/3 前值 + 1/3 当前）
- atr 用 StockCharts 式：首个 = 前 n 个 TR 均值，之后 Wilder 平滑
"""

import numpy as np
import pandas as pd


def ma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    """相对强弱指标（Wilder 平滑）。全涨 -> 100，全跌 -> 0。"""
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD：返回 (dif, dea, hist)，hist = 2*(dif - dea)（国内惯例）。"""
    dif = ema(s, fast) - ema(s, slow)
    dea = ema(dif, signal)
    hist = 2 * (dif - dea)
    return dif, dea, hist


def kdj(df: pd.DataFrame, n: int = 9):
    """KDJ：需要 df 含 high/low/close 列，返回 (K, D, J)。"""
    h, l, c = df["high"], df["low"], df["close"]
    # min_periods=1：窗口不足 n 时用已有数据（与参考实现一致），仅 hi==lo 记 50
    low_n = l.rolling(n, min_periods=1).min()
    high_n = h.rolling(n, min_periods=1).max()
    rsv = ((c - low_n) / (high_n - low_n) * 100).fillna(50.0)
    k = rsv.ewm(com=2, adjust=False).mean()   # com=2 -> alpha=1/3
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """平均真实波幅（StockCharts 式）。需要 df 含 high/low/close 列。"""
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    tr.iloc[0] = h.iloc[0] - l.iloc[0]
    values = np.full(len(df), np.nan)
    a = 1 / n
    for i in range(n - 1, len(df)):
        values[i] = tr.iloc[:n].mean() if i == n - 1 else (values[i - 1] * (n - 1) + tr.iloc[i]) / n
    return pd.Series(values, index=df.index)


def boll(s: pd.Series, n: int = 20, k: float = 2.0):
    """布林带：返回 (中轨, 上轨, 下轨)。"""
    mid = s.rolling(n).mean()
    std = s.rolling(n).std()
    return mid, mid + k * std, mid - k * std
