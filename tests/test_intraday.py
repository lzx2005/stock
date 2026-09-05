from datacenter import DataCenter
from tests.conftest import FakeClock, FakeTickFlow, make_kline_df
from datacenter.intraday import IntradayCache

T0, DAY = 1754011800000, 86_400_000  # 2025-08-01 09:30 北京时间


def test_intraday_cached_within_ttl():
    cache = IntradayCache(ttl_sec=60)
    calls = []

    def fetch():
        calls.append(1)
        return make_kline_df("600000.SH", T0, 3, 60_000)

    cache.get_or_fetch("600000.SH", "1m", fetch)
    cache.get_or_fetch("600000.SH", "1m", fetch)
    assert len(calls) == 1  # TTL 内不重复请求


def test_intraday_refetch_after_ttl():
    clock = FakeClock()
    cache = IntradayCache(ttl_sec=60, now=clock.now)
    calls = []

    def fetch():
        calls.append(1)
        return make_kline_df("600000.SH", T0, 3, 60_000)

    cache.get_or_fetch("600000.SH", "1m", fetch)
    clock.t += 61
    cache.get_or_fetch("600000.SH", "1m", fetch)
    assert len(calls) == 2


def test_get_klines_intraday_day_uses_intraday_api(tmp_path):
    """end_ms 落在今日（时钟注入）-> 当日段走 intraday 接口，且不记永久 coverage。"""
    fake = FakeTickFlow(symbols=["600000.SH"])
    now = T0 + 4 * 3600_000  # 当日 13:30（T0 为 09:30）
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake, now_ms=lambda: now)
    fake.klines.intraday_df = make_kline_df("600000.SH", T0, 3, 60_000)  # 今日 3 根 1m
    df = dc.get_klines("600000.SH", "1m", T0 - 10 * DAY, now)
    # 历史 1m 无覆盖 -> 回源得空（FakeKlines 队列空返回空 df）；当日段来自 intraday
    assert len(df) == 3
    assert df["timestamp"].min() >= T0
    # 当日段不得记入永久覆盖区间（否则明日查询会误判今日已缓存）
    cov = dc.meta.get_coverage("600000.SH", "1m")
    assert cov is None or cov[1] < T0


def test_get_klines_daily_today_aggregates_from_intraday(tmp_path):
    """日线查询跨今日：不调 get_intraday(\"1d\")，而是聚合当日 1m -> 一根日线 bar。"""
    fake = FakeTickFlow(symbols=["600000.SH"])
    now = T0 + 4 * 3600_000  # 当日 13:30
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake, now_ms=lambda: now)
    # 今日 3 根 1m：open 递增、close 递增，用于验证聚合首/末/高低
    m = make_kline_df("600000.SH", T0, 3, 60_000)
    m.loc[:, "open"] = [10.0, 10.2, 10.4]
    m.loc[:, "high"] = [10.5, 10.6, 10.8]
    m.loc[:, "low"] = [9.9, 10.1, 10.3]
    m.loc[:, "close"] = [10.1, 10.3, 10.5]
    m.loc[:, "volume"] = [100, 200, 300]
    fake.klines.intraday_df = m
    df = dc.get_klines("600000.SH", "1d", T0 - 10 * DAY, now)
    assert len(df) == 1  # 无历史覆盖 -> 只有今日聚合 bar
    bar = df.iloc[0]
    assert bar["open"] == 10.0 and bar["close"] == 10.5
    assert bar["high"] == 10.8 and bar["low"] == 9.9
    assert bar["volume"] == 600
    today_start = now - ((now + 8 * 3600_000) % 86_400_000)  # 北京当日 0 点
    assert bar["timestamp"] == today_start
    # 当日不记永久 coverage
    cov = dc.meta.get_coverage("600000.SH", "1d")
    assert cov is None or cov[1] < T0
    # 只调了一次 intraday 1m（用于聚合）；绝不调 intraday 的 "1d"
    assert fake.klines.intraday_calls == 1
