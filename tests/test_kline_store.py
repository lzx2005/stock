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


def test_read_empty_store_returns_empty(store):
    out = store.read(["600000.SH"], "1d", 0, 10**13)
    assert out.empty
    assert "symbol" in out.columns and "timestamp" in out.columns


def test_read_roundtrip(store):
    df = make_kline_df("600000.SH", T0, 10, DAY)
    store.write(df, "1d", tag="a")
    out = store.read(["600000.SH"], "1d", T0, T0 + 10 * DAY)
    assert len(out) == 10
    assert list(out["timestamp"]) == sorted(df["timestamp"])


def test_read_filters_by_range_and_symbols(store):
    store.write(make_kline_df("600000.SH", T0, 10, DAY), "1d", tag="a")
    store.write(make_kline_df("000001.SZ", T0, 10, DAY), "1d", tag="a")
    out = store.read(["600000.SH"], "1d", T0 + 2 * DAY, T0 + 5 * DAY)
    assert len(out) == 4
    assert set(out["symbol"]) == {"600000.SH"}


def test_read_dedup_last_write_wins(store):
    df1 = make_kline_df("600000.SH", T0, 5, DAY)           # close = base+0.5
    store.write(df1, "1d", tag="old")
    df2 = df1.copy()
    df2["close"] = 999.0                                    # 修正数据后写
    store.write(df2, "1d", tag="fix")
    out = store.read(["600000.SH"], "1d", T0, T0 + 5 * DAY)
    assert len(out) == 5
    assert (out["close"] == 999.0).all()


def test_read_is_readonly_and_repeatable(store):
    store.write(make_kline_df("600000.SH", T0, 5, DAY), "1d", tag="a")
    out1 = store.read(["600000.SH"], "1d", 0, 10**13)
    out2 = store.read(["600000.SH"], "1d", 0, 10**13)
    pd.testing.assert_frame_equal(out1, out2)


# ---- 加固③：.tmp 文件防护 ----

def test_read_ignores_stray_tmp_files(store, tmp_path):
    """崩溃残留的 .tmp-*.parquet（内容有效）不得被读取端 glob 命中。"""
    store.write(make_kline_df("600000.SH", T0, 5, DAY), "1d", tag="good")
    part_dir = tmp_path / "klines" / "period=1d" / "year=2025"
    part_dir.mkdir(parents=True, exist_ok=True)
    stray = make_kline_df("600000.SH", T0 + 100 * DAY, 3, DAY)  # 2025-11，同 year 分区
    stray.to_parquet(part_dir / ".tmp-20990101000000000000-stray.parquet", index=False)
    out = store.read(["600000.SH"], "1d", 0, 10**13)
    assert len(out) == 5  # 不含 .tmp 里的 3 行


def test_write_cleans_tmp_on_failure(store, tmp_path, monkeypatch):
    """to_parquet/rename 中途失败时清理 .tmp，且异常照常抛出。"""
    import os

    df = make_kline_df("600000.SH", T0, 5, DAY)

    def boom(*args, **kwargs):
        raise OSError("simulated crash during rename")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.write(df, "1d", tag="crash")
    tmps = list((tmp_path / "klines").rglob(".tmp-*"))
    assert tmps == []


# ---- KlineStore.count ----

def test_count_matches_read(store):
    df = make_kline_df("600000.SH", T0, 10, DAY)
    store.write(df, "1d", tag="a")
    assert store.count(["600000.SH"], "1d", T0, T0 + 10 * DAY) == 10


def test_count_filters_range_and_dedup(store):
    df1 = make_kline_df("600000.SH", T0, 5, DAY)
    store.write(df1, "1d", tag="old")
    df2 = df1.copy()
    df2["close"] = 999.0                     # 修正数据后写，去重"后写胜出"
    store.write(df2, "1d", tag="fix")
    assert store.count(["600000.SH"], "1d", T0, T0 + 5 * DAY) == 5
    assert store.count(["600000.SH"], "1d", T0 + 2 * DAY, T0 + 3 * DAY) == 2


def test_count_empty_and_no_symbols(store):
    assert store.count(["600000.SH"], "1d", 0, 10**13) == 0
    assert store.count([], "1d", 0, 10**13) == 0


# ---- 并发读加固：duckdb 默认连接线程不安全（webui 点击并发 klines → 500）----

def test_concurrent_reads_thread_safe(store):
    """两个线程同时 read/count 必须全部成功。

    根因：duckdb.sql() 走进程级默认连接，线程不安全——并发查询抛
    InvalidInputException（甚至死锁）。用 barrier 对齐起跑 + 30 轮放大命中率。
    """
    from concurrent.futures import ThreadPoolExecutor
    import threading

    df = make_kline_df("600000.SH", T0, 10, DAY)
    store.write(df, "1d", tag="t")
    start, end = T0, T0 + 9 * DAY
    barrier = threading.Barrier(2)

    def do(_):
        barrier.wait()
        return (len(store.read(["600000.SH"], "1d", start, end)),
                store.count(["600000.SH"], "1d", start, end))

    with ThreadPoolExecutor(max_workers=2) as ex:
        for _ in range(30):
            for rows, n in ex.map(do, range(2)):
                assert rows == 10 and n == 10
