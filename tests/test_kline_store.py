import pandas as pd
import pytest

from datacenter.store.klines import KlineStore
from tests.conftest import make_kline_df

# 2025-08-01 09:30:00 Asia/Shanghai = 1754011800000 ms
T0 = 1754011800000
MIN = 60_000
DAY = 86_400_000


@pytest.fixture
def store(tmp_path):
    return KlineStore(tmp_path / "klines")


def test_write_creates_minute_partition_with_month(store):
    df = make_kline_df("600000.SH", T0, 10, MIN)
    written = store.write(df, "1m", tag="test")
    assert len(written) == 1
    path = written[0]
    assert "period=1m" in str(path) and "year=2025" in str(path) and "month=08" in str(path)
    assert path.name.startswith("part-") and path.name.endswith("-test.parquet")
    assert path.exists()


def test_write_daily_partition_without_month(store):
    df = make_kline_df("600000.SH", T0, 5, DAY)
    written = store.write(df, "1d", tag="test")
    assert "month=" not in str(written[0])


def test_write_splits_across_months(store):
    # 跨 8/9 月的数据拆成两个分区文件（2025-08-01 起每5天一根，10 根跨 45 天）
    df = make_kline_df("600000.SH", T0, 10, 5 * DAY)
    written = store.write(df, "1m", tag="test")
    assert len(written) == 2


def test_write_empty_is_noop(store):
    assert store.write(pd.DataFrame(), "1d", tag="test") == []


def test_no_tmp_files_left(store, tmp_path):
    df = make_kline_df("600000.SH", T0, 10, MIN)
    store.write(df, "1m", tag="test")
    tmps = list((tmp_path / "klines").rglob(".tmp-*"))
    assert tmps == []
