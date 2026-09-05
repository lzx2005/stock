import pytest

from datacenter import DataCenter
from datacenter.quality import (cross_check_minute_daily, find_gaps,
                                repair_gaps, sample_compare, trading_calendar)
from tests.conftest import FakeTickFlow, make_kline_df

T0, DAY = 1754011800000, 86_400_000


def test_trading_calendar_from_index(tmp_path):
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=FakeTickFlow())
    dc.klines.write(make_kline_df("000001.SH", T0, 5, DAY), "1d", tag="test")
    cal = trading_calendar(dc, T0, T0 + 5 * DAY)
    assert len(cal) == 5


def test_find_gaps_detects_missing_days(tmp_path):
    """一只股缺了中间两天 -> find_gaps 报出缺口区间。"""
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=FakeTickFlow())
    dc.klines.write(make_kline_df("000001.SH", T0, 5, DAY), "1d", tag="cal")
    df = make_kline_df("600000.SH", T0, 5, DAY)
    df = df.drop([1, 2])  # 挖洞：缺 T0+D、T0+2D
    dc.klines.write(df, "1d", tag="test")
    gaps = find_gaps(dc, "600000.SH", "1d", T0, T0 + 5 * DAY)
    assert gaps == [(T0 + DAY, T0 + 2 * DAY)]


def test_find_gaps_rejects_minute(tmp_path):
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=FakeTickFlow())
    with pytest.raises(ValueError):
        find_gaps(dc, "600000.SH", "1m", T0, T0 + DAY)


def test_repair_gaps_refetches_via_client(tmp_path):
    """repair_gaps 绕过 coverage 直接回源：fake 队列里的数据被拉回写入。"""
    fake = FakeTickFlow()
    fake.klines.queue(make_kline_df("600000.SH", T0, 5, DAY))
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    gaps = [(T0 + DAY, T0 + 2 * DAY)]
    repair_gaps(dc, "600000.SH", gaps)
    df = dc.klines.read(["600000.SH"], "1d", T0, T0 + 5 * DAY)
    assert len(df) == 5  # 补拉后 5 根齐全


def test_sample_compare_detects_mismatch(tmp_path):
    fake = FakeTickFlow()
    fake.klines.queue(make_kline_df("600000.SH", T0, 5, DAY))  # 回源数据
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    local = make_kline_df("600000.SH", T0, 5, DAY)
    local.loc[0, "close"] = 999.0  # 本地被篡改
    dc.klines.write(local, "1d", tag="bad")
    dc.meta.extend_coverage("600000.SH", "1d", T0, T0 + 5 * DAY)
    bad = sample_compare(dc, ["600000.SH"], "1d", T0, T0 + 5 * DAY)
    assert bad == ["600000.SH"]


def test_minute_daily_cross_check(tmp_path):
    """1m 聚合 volume/amount 应等于当日 1d（容差 1%）。"""
    fake = FakeTickFlow()
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    # 构造当日 3 根 1m 线（volume=100/200/300, amount=1000/2000/3000）
    m1 = make_kline_df("600000.SH", T0, 3, 60_000)
    m1["volume"] = [100, 200, 300]
    m1["amount"] = [1000.0, 2000.0, 3000.0]
    dc.klines.write(m1, "1m", tag="test")
    # 当日 1d：volume=600, amount=6000 -> 一致
    d1 = make_kline_df("600000.SH", T0, 1, DAY)
    d1["volume"] = [600]
    d1["amount"] = [6000.0]
    dc.klines.write(d1, "1d", tag="test")
    assert cross_check_minute_daily(dc, "600000.SH", date_ms=T0) == []
    # 篡改 1d 的 volume -> 报不一致
    d2 = d1.copy()
    d2["volume"] = [9999]
    dc.klines.write(d2, "1d", tag="bad")  # 后写胜出
    mismatches = cross_check_minute_daily(dc, "600000.SH", date_ms=T0)
    assert mismatches == ["600000.SH"]
