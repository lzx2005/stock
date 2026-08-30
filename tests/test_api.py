import pytest

from datacenter import DataCenter
from tests.conftest import FakeTickFlow, make_kline_df

T0, DAY = 1754011800000, 86_400_000


@pytest.fixture
def dc(tmp_path):
    fake = FakeTickFlow(symbols=["600000.SH", "000001.SZ"])
    fake.klines.queue(make_kline_df("600000.SH", T0, 10, DAY))
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake, rate_per_sec=1000)
    return dc, fake


def test_get_klines_end_to_end(dc):
    dc_, fake = dc
    df = dc_.get_klines("600000.SH", "1d", T0, T0 + 10 * DAY)
    assert len(df) == 10
    assert df["timestamp"].is_monotonic_increasing
    # 第二次完全走缓存
    df2 = dc_.get_klines("600000.SH", "1d", T0, T0 + 10 * DAY)
    assert len(df2) == 10
    assert len(fake.klines.calls) == 1


def test_get_klines_validates_period(dc):
    dc_, _ = dc
    with pytest.raises(ValueError):
        dc_.get_klines("600000.SH", "2d", T0, T0 + DAY)


def test_list_symbols_populates_instruments(dc):
    dc_, fake = dc
    symbols = dc_.list_symbols()
    assert symbols == ["000001.SZ", "600000.SH"]
    assert dc_.list_symbols() == ["000001.SZ", "600000.SH"]  # 走本地
