import pytest

from datacenter import DataCenter
from tests.conftest import FakeInstruments, FakeTickFlow, make_kline_df

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


def test_get_klines_forward_adjust(dc):
    dc_, fake = dc  # fixture 已预置 10 根日线，close 恒为 C = base+0.5
    fake.klines.ex_factors.set([(T0 + 5 * DAY, 2.0)])  # 第 6 根为除权日（校准：factor>1）
    df = dc_.get_klines("600000.SH", "1d", T0, T0 + 10 * DAY, adjust="forward")
    c = make_kline_df("600000.SH", T0, 1, DAY)["close"].iloc[0]  # 原始价 C
    assert df["close"].iloc[0] == pytest.approx(c * 0.5)   # 除权日前 ×(1/2)
    assert df["close"].iloc[4] == pytest.approx(c * 0.5)
    assert df["close"].iloc[5] == pytest.approx(c)         # 除权日起不变
    assert df["close"].iloc[-1] == pytest.approx(c)


def test_get_klines_additive_falls_through_to_remote(dc):
    dc_, fake = dc
    fake.klines.queue(make_kline_df("600000.SH", T0, 10, DAY))
    df = dc_.get_klines("600000.SH", "1d", T0, T0 + 10 * DAY, adjust="forward_additive")
    assert len(df) == 10
    # 穿透回源：adjust 参数原样传给远程，不读缓存
    assert fake.klines.calls[-1]["adjust"] == "forward_additive"


def test_instrument_metadata_cached(tmp_path):
    fake = FakeTickFlow(symbols=["600000.SH"])
    fake.instruments = FakeInstruments({"600000.SH": {"symbol": "600000.SH", "name": "浦发银行",
                                        "exchange": "SH", "code": "600000", "region": "CN"}})
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    inst = dc.get_instruments(["600000.SH"])
    assert inst["600000.SH"]["name"] == "浦发银行"
    dc.get_instruments(["600000.SH"])  # 第二次不回源
    assert fake.instruments.calls == 1


def test_universe_members_cached(tmp_path):
    fake = FakeTickFlow(symbols=["a.SH", "b.SH"])
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    dc.list_symbols()  # 触发回源
    assert dc.get_universe_symbols("CN_Equity_A") == ["a.SH", "b.SH"]
