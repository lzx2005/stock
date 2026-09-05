import pandas as pd
import pytest
from tests.conftest import make_kline_df
import backtest.indicators as ind
import factors.factors  # noqa: F401  —— import 即注册
from factors.compute import apply_factor
from factors.registry import get_factor, FactorInputError

def _df(n=60):
    df = make_kline_df("600000.SH", start_ms=0, n=n, step_ms=86_400_000)  # 日线
    # 给价格一点变化，让 rolling 值非平凡
    df["close"] = df["close"] + df["close"] * pd.Series(range(n)).astype(float) / 1000
    df["volume"] = 1000 + pd.Series(range(n))
    return df

def _apply(name, df, params=None):
    """apply_factor 的便捷封装：get_factor 返回 (defn, merged, fp)，显式解构避免参数错位。"""
    defn, merged, _ = get_factor(name, params)
    return apply_factor(defn, df, merged)

def test_apply_ma_matches_indicators():
    df = _df()
    out = _apply("ma", df, {"n": 5})
    pd.testing.assert_series_equal(out, ind.ma(df["close"], 5), check_names=False)

def test_apply_rsi_matches_indicators():
    df = _df()
    out = _apply("rsi", df)
    pd.testing.assert_series_equal(out, ind.rsi(df["close"], 14), check_names=False)

def test_apply_macd_hist_matches_indicators():
    df = _df()
    dif, dea, hist = ind.macd(df["close"])
    out = _apply("macd_hist", df)
    pd.testing.assert_series_equal(out, hist, check_names=False)

def test_apply_kdj_j_and_boll_match():
    df = _df()
    _, _, j = ind.kdj(df)
    pd.testing.assert_series_equal(_apply("kdj_j", df), j,
                                   check_names=False)          # 头段 NaN 按相等处理
    mid, up, low = ind.boll(df["close"])
    pd.testing.assert_series_equal(_apply("boll_up", df), up, check_names=False)

def test_vol_ratio_manual():
    df = _df()
    out = _apply("vol_ratio", df, {"n": 5})
    # 与原始 pandas 表达式逐点对拍；NaN 位置用 assert_series_equal 相等处理
    pd.testing.assert_series_equal(out, df["volume"] / df["volume"].rolling(5).mean(),
                                   check_names=False)

def test_mom_manual():
    df = _df()
    pd.testing.assert_series_equal(_apply("mom", df, {"n": 5}),
                                   df["close"].pct_change(5), check_names=False)

def test_bias_manual():
    df = _df()
    m = ind.ma(df["close"], 20)
    pd.testing.assert_series_equal(_apply("bias", df), (df["close"] - m) / m,
                                   check_names=False)

def test_apply_ema_atr_boll_low_match_indicators():
    df = _df()
    pd.testing.assert_series_equal(_apply("ema", df), ind.ema(df["close"], 12), check_names=False)
    pd.testing.assert_series_equal(_apply("atr", df), ind.atr(df, 14), check_names=False)
    _, _, low = ind.boll(df["close"])
    pd.testing.assert_series_equal(_apply("boll_low", df), low, check_names=False)

def test_missing_input_raises():
    df = _df().drop(columns=["volume"])
    with pytest.raises(FactorInputError):
        _apply("vol_ratio", df)
