import pytest

from datacenter.jobs.ws_collector import Collector
from datacenter.store.realtime import RealtimeStore


def test_buffer_flushes_at_count(tmp_path):
    store = RealtimeStore(tmp_path / "realtime")
    c = Collector(store, flush_interval=3600, flush_count=3)
    for i in range(3):
        c.on_message({"symbol": "s", "ts_ms": i, "last_price": 1.0,
                      "volume": 1, "turnover": 1.0})
    assert len(store.read("s", 0, 10)) == 3  # 满 3 条自动落盘


def test_buffer_flushes_on_timer(tmp_path):
    store = RealtimeStore(tmp_path / "realtime")
    c = Collector(store, flush_interval=5.0, flush_count=1000)
    c.on_message({"symbol": "s", "ts_ms": 1, "last_price": 1.0, "volume": 1, "turnover": 1.0})
    c.maybe_flush(now=6.0)  # 超过间隔
    assert len(store.read("s", 0, 10)) == 1


def test_malformed_message_dropped_with_log(tmp_path, caplog):
    store = RealtimeStore(tmp_path / "realtime")
    c = Collector(store)
    c.on_message({"garbage": True})  # 缺字段不崩溃
    assert store.read("s", 0, 10).empty
