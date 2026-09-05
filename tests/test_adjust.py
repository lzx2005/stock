import numpy as np
import pandas as pd
import pytest

from datacenter.adjust import apply_adjust
from tests.conftest import make_kline_df

DAY = 86_400_000
T0 = 1700000000000


def _df_with_closes(closes, start=T0):
    n = len(closes)
    df = make_kline_df("600000.SH", start, n, DAY)
    df["close"] = df["open"] = df["high"] = df["low"] = closes
    df["volume"] = 1000
    return df


def test_none_returns_raw():
    df = _df_with_closes([10.0, 10.0, 10.0])
    out = apply_adjust(df, [], "none")
    pd.testing.assert_frame_equal(out, df)


def test_forward_adjust_scales_history_down():
    """校准结论：factor>1 表示除权日价格回落比例，前复权 = 除权日前历史价 × (1/factor)。
    除权日在第 3 根（T0+2D），factor=2.0（价 10->5）：前两根 ×0.5，量÷0.5，当日及以后不变。"""
    df = _df_with_closes([10.0, 10.0, 5.0])  # 10->5 除权
    factors = [(T0 + 2 * DAY, 2.0)]
    out = apply_adjust(df, factors, "forward")
    assert list(out["close"]) == [5.0, 5.0, 5.0]
    assert list(out["volume"]) == [2000, 2000, 1000]


def test_backward_adjust_scales_future():
    """后复权：历史不变，除权日及以后 × factor（价格抬高回去）。"""
    df = _df_with_closes([10.0, 10.0, 5.0])
    factors = [(T0 + 2 * DAY, 2.0)]
    out = apply_adjust(df, factors, "backward")
    assert list(out["close"]) == [10.0, 10.0, 10.0]
    assert list(out["volume"]) == [1000, 1000, 500]  # 除权日起量 ÷ 价格缩放


def test_multiple_ex_dates_cumulative():
    """两次除权累积：第1根在两次除权前 → ×(1/2)×(1/2)；第2根在第二次前 → ×(1/2)。"""
    df = _df_with_closes([10.0, 8.0, 5.0])
    factors = [(T0 + DAY, 2.0), (T0 + 2 * DAY, 2.0)]  # 两次除权
    out = apply_adjust(df, factors, "forward")
    assert np.isclose(out["close"].iloc[0], 10.0 * 0.5 * 0.5)
    assert np.isclose(out["close"].iloc[1], 8.0 * 0.5)
    assert np.isclose(out["close"].iloc[2], 5.0)


def test_empty_factors_is_identity():
    df = _df_with_closes([10.0, 11.0])
    out = apply_adjust(df, [], "forward")
    pd.testing.assert_frame_equal(out, df)


def test_unsupported_additive_raises():
    df = _df_with_closes([10.0, 11.0])
    with pytest.raises(ValueError):
        apply_adjust(df, [(T0 + DAY, 2.0)], "forward_additive")
