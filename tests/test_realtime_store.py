import pandas as pd
import pytest

from datacenter.store.realtime import RealtimeStore


@pytest.fixture
def store(tmp_path):
    return RealtimeStore(tmp_path / "realtime")


def test_write_read_roundtrip(store):
    rows = pd.DataFrame([
        {"symbol": "600000.SH", "ts_ms": 1754011800000, "last_price": 10.5,
         "volume": 1000, "turnover": 10500.0, "kind": "snapshot"},
        {"symbol": "600000.SH", "ts_ms": 1754011803000, "last_price": 10.6,
         "volume": 1200, "turnover": 12720.0, "kind": "snapshot"},
    ])
    store.write(rows)
    out = store.read("600000.SH", 1754011800000, 1754011803000)
    assert len(out) == 2
    assert out["ts_ms"].is_monotonic_increasing


def test_partition_by_shanghai_date(store):
    # 北京时间 2025-08-01 09:30 与 15:00 -> 同一 date 分区
    rows = pd.DataFrame([
        {"symbol": "s", "ts_ms": 1754011800000, "last_price": 1.0,
         "volume": 1, "turnover": 1.0, "kind": "snapshot"},
        {"symbol": "s", "ts_ms": 1754031600000, "last_price": 2.0,
         "volume": 2, "turnover": 2.0, "kind": "snapshot"},
    ])
    written = store.write(rows)
    assert len(written) == 1
    assert "date=2025-08-01" in str(written[0])


def test_read_empty(store):
    assert store.read("x.SH", 0, 10**13).empty
