import pytest
from datacenter.store.meta import MetaStore


@pytest.fixture
def meta(tmp_path):
    return MetaStore(tmp_path / "meta.db")


def test_coverage_none_initially(meta):
    assert meta.get_coverage("600000.SH", "1d") is None


def test_set_then_extend_coverage(meta):
    meta.extend_coverage("600000.SH", "1d", 1000, 2000)
    assert meta.get_coverage("600000.SH", "1d") == (1000, 2000)
    meta.extend_coverage("600000.SH", "1d", 500, 1500)   # 向左扩展
    assert meta.get_coverage("600000.SH", "1d") == (500, 2000)
    meta.extend_coverage("600000.SH", "1d", 2000, 3000)  # 向右扩展
    assert meta.get_coverage("600000.SH", "1d") == (500, 3000)
    meta.extend_coverage("600000.SH", "1d", 800, 900)    # 子区间不收缩
    assert meta.get_coverage("600000.SH", "1d") == (500, 3000)


def test_coverage_per_symbol_period(meta):
    meta.extend_coverage("600000.SH", "1d", 1000, 2000)
    assert meta.get_coverage("000001.SZ", "1d") is None
    assert meta.get_coverage("600000.SH", "1m") is None


def test_sync_job_status_roundtrip(meta):
    assert meta.pending_symbols(["a", "b"], "1d") == ["a", "b"]
    meta.mark_done("a", "1d")
    assert meta.pending_symbols(["a", "b"], "1d") == ["b"]
    meta.mark_done("a", "1m")  # 不影响 1d 的判定
    assert meta.pending_symbols(["a", "b"], "1d") == ["b"]


def test_instruments_upsert_and_count(meta):
    meta.upsert_symbols(["600000.SH", "000001.SZ"])
    assert meta.symbol_count() == 2
    meta.upsert_symbols(["600000.SH", "600519.SH"])  # 幂等
    assert meta.symbol_count() == 3
    assert meta.all_symbols() == ["000001.SZ", "600000.SH", "600519.SH"]
