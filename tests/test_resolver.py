import pytest

from datacenter.resolver import CacheResolver, missing_segments
from tests.conftest import FakeTickFlow, make_kline_df

T0, DAY = 1754011800000, 86_400_000


def test_missing_segments_no_coverage():
    assert missing_segments(100, 200, None) == [(100, 200)]


def test_missing_segments_full_hit():
    assert missing_segments(120, 180, (100, 200)) == []


def test_missing_segments_left_and_right():
    assert missing_segments(50, 300, (100, 200)) == [(50, 99), (201, 300)]


@pytest.fixture
def env(tmp_path, fake_tf):
    from datacenter.store.meta import MetaStore
    from datacenter.store.klines import KlineStore
    from datacenter.client.tickflow_client import TickFlowClient
    meta = MetaStore(tmp_path / "meta.db")
    store = KlineStore(tmp_path / "klines")
    client = TickFlowClient(tf=fake_tf, rate_per_sec=1000, sleep=lambda s: None)
    return CacheResolver(meta=meta, klines=store, client=client), fake_tf, meta


def test_full_miss_fetches_and_caches(env):
    resolver, fake_tf, meta = env
    fake_tf.klines.queue(make_kline_df("600000.SH", T0, 5, DAY))
    resolver.ensure("600000.SH", "1d", T0, T0 + 5 * DAY)
    assert meta.get_coverage("600000.SH", "1d") == (T0, T0 + 5 * DAY)
    assert len(fake_tf.klines.calls) == 1
    # 二次查询不回源
    resolver.ensure("600000.SH", "1d", T0, T0 + 5 * DAY)
    assert len(fake_tf.klines.calls) == 1


def test_empty_remote_result_still_marks_coverage(env):
    """未上市/停牌区间回源为空，也必须标记覆盖，防止反复打空。"""
    resolver, fake_tf, meta = env
    import pandas as pd
    fake_tf.klines.queue(pd.DataFrame())
    resolver.ensure("600000.SH", "1d", T0, T0 + 5 * DAY)
    assert meta.get_coverage("600000.SH", "1d") == (T0, T0 + 5 * DAY)
    resolver.ensure("600000.SH", "1d", T0, T0 + 5 * DAY)
    assert len(fake_tf.klines.calls) == 1


def test_partial_miss_only_fetches_gaps(env):
    resolver, fake_tf, meta = env
    fake_tf.klines.queue(make_kline_df("600000.SH", T0, 5, DAY))
    resolver.ensure("600000.SH", "1d", T0, T0 + 5 * DAY)
    # 扩展请求右侧 3 天：只回源缺口段
    fake_tf.klines.queue(make_kline_df("600000.SH", T0 + 5 * DAY + 1, 3, DAY))
    resolver.ensure("600000.SH", "1d", T0, T0 + 8 * DAY)
    last = fake_tf.klines.calls[-1]
    assert last["start_time"] == T0 + 5 * DAY + 1
    assert meta.get_coverage("600000.SH", "1d") == (T0, T0 + 8 * DAY)
