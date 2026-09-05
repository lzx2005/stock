"""指标库测试：与独立循环参考实现逐点对拍（避免魔法数/自指）。

RSI/MACD 参考实现语义与 pandas ewm(adjust=False) 一致：
- 第一个有效值作为种子，之后 y_t = (1-a)*y_{t-1} + a*x_t
- 实现方与参考方共用该语义，逐点 allclose（equal_nan）。
"""
import numpy as np
import pandas as pd
import pytest

from backtest.indicators import atr, boll, ema, kdj, ma, macd, rsi


def _mk_ohlc(close):
    """由收盘价序列生成确定性 OHLC（合成测试数据）。"""
    close = np.asarray(close, dtype=float)
    n = len(close)
    high = np.maximum(close, np.roll(close, 1)) + 0.5
    high[0] = close[0] + 0.5
    low = np.minimum(close, np.roll(close, 1)) - 0.5
    low[0] = close[0] - 0.5
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close})


def _ref_rsi(close, n=14):
    close = np.asarray(close, dtype=float)
    a = 1.0 / n
    gain = np.zeros(len(close))
    loss = np.zeros(len(close))
    for i in range(1, len(close)):
        d = close[i] - close[i - 1]
        gain[i] = max(d, 0.0)
        loss[i] = max(-d, 0.0)
    avg_g = np.full(len(close), np.nan)
    avg_l = np.full(len(close), np.nan)
    for i in range(1, len(close)):
        if np.isnan(avg_g[i - 1]):
            avg_g[i], avg_l[i] = gain[i], loss[i]
        else:
            avg_g[i] = (1 - a) * avg_g[i - 1] + a * gain[i]
            avg_l[i] = (1 - a) * avg_l[i - 1] + a * loss[i]
    out = np.full(len(close), np.nan)
    for i in range(1, len(close)):
        out[i] = 100.0 if avg_l[i] == 0 else 100 - 100 / (1 + avg_g[i] / avg_l[i])
    return out


def _ref_ema(s, n):
    s = np.asarray(s, dtype=float)
    a = 2.0 / (n + 1)
    y = np.full(len(s), np.nan)
    y[0] = s[0]
    for i in range(1, len(s)):
        y[i] = (1 - a) * y[i - 1] + a * s[i]
    return y


@pytest.fixture
def closes():
    rng = np.random.default_rng(42)
    return np.round(np.cumsum(rng.normal(0, 1, 200)) + 100, 2)


def test_ma_matches_rolling(closes):
    s = pd.Series(closes)
    out = ma(s, 5)
    assert out.iloc[4] == pytest.approx(s.iloc[:5].mean())
    assert np.allclose(out.dropna().values, s.rolling(5).mean().dropna().values)


def test_ema_matches_reference(closes):
    s = pd.Series(closes)
    assert np.allclose(ema(s, 12).values, _ref_ema(closes, 12), rtol=1e-10, equal_nan=True)


def test_rsi_matches_reference(closes):
    s = pd.Series(closes)
    assert np.allclose(rsi(s, 14).values, _ref_rsi(closes, 14), rtol=1e-9, equal_nan=True)


def test_rsi_bounds_monotonic_up():
    s = pd.Series(np.arange(1.0, 40.0))  # 单调上涨
    out = rsi(s, 5)
    assert np.isnan(out.iloc[0])
    assert np.allclose(out.dropna().values, 100.0)


def test_rsi_bounds_monotonic_down():
    s = pd.Series(np.arange(40.0, 1.0, -1.0))
    out = rsi(s, 5)
    assert np.allclose(out.dropna().values, 0.0)


def test_macd_matches_reference(closes):
    dif_ref = _ref_ema(closes, 12) - _ref_ema(closes, 26)
    dea_ref = _ref_ema(dif_ref, 9)
    hist_ref = 2 * (dif_ref - dea_ref)
    dif, dea, hist = macd(pd.Series(closes))
    assert np.allclose(dif.values, dif_ref, rtol=1e-9, equal_nan=True)
    assert np.allclose(dea.values, dea_ref, rtol=1e-9, equal_nan=True)
    assert np.allclose(hist.values, hist_ref, rtol=1e-9, equal_nan=True)


def test_kdj_matches_reference(closes):
    df = _mk_ohlc(closes)
    k_ref = np.full(len(df), np.nan)
    d_ref = np.full(len(df), np.nan)
    H, L, C = df["high"].values, df["low"].values, df["close"].values
    for i in range(len(df)):
        lo = min(L[max(0, i - 8):i + 1])
        hi = max(H[max(0, i - 8):i + 1])
        rsv = 50.0 if hi == lo else (C[i] - lo) / (hi - lo) * 100
        k_ref[i] = 2 / 3 * (k_ref[i - 1] if i > 0 else 50.0) + 1 / 3 * rsv
        d_ref[i] = 2 / 3 * (d_ref[i - 1] if i > 0 else 50.0) + 1 / 3 * k_ref[i]
    j_ref = 3 * k_ref - 2 * d_ref
    k, d, j = kdj(df)
    assert np.allclose(k.values, k_ref, rtol=1e-9, equal_nan=True)
    assert np.allclose(d.values, d_ref, rtol=1e-9, equal_nan=True)
    assert np.allclose(j.values, j_ref, rtol=1e-9, equal_nan=True)


def test_atr_matches_reference(closes):
    df = _mk_ohlc(closes)
    H, L, C = df["high"].values, df["low"].values, df["close"].values
    tr = np.full(len(df), np.nan)
    tr[0] = H[0] - L[0]
    for i in range(1, len(df)):
        tr[i] = max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
    ref = np.full(len(df), np.nan)
    n = 14
    for i in range(n - 1, len(df)):
        ref[i] = tr[:n].mean() if i == n - 1 else (ref[i - 1] * (n - 1) + tr[i]) / n
    assert np.allclose(atr(df, n).values, ref, rtol=1e-9, equal_nan=True)


def test_boll_matches_rolling(closes):
    s = pd.Series(closes)
    mid, upper, lower = boll(s, 20, 2.0)
    m_ref = s.rolling(20).mean()
    u_ref = m_ref + 2 * s.rolling(20).std()
    l_ref = m_ref - 2 * s.rolling(20).std()
    assert np.allclose(mid.dropna().values, m_ref.dropna().values)
    assert np.allclose(upper.dropna().values, u_ref.dropna().values)
    assert np.allclose(lower.dropna().values, l_ref.dropna().values)
