import time

import pytest
from datacenter.store.meta import MetaStore


@pytest.fixture
def meta(tmp_path):
    return MetaStore(tmp_path / "meta.db")


def test_instrument_metadata_roundtrip(meta):
    meta.upsert_instruments([{"symbol": "600000.SH", "name": "浦发银行",
                              "exchange": "SH", "code": "600000", "region": "CN"}])
    inst = meta.get_instrument("600000.SH")
    assert inst["name"] == "浦发银行"
    assert inst["region"] == "CN"


def test_universe_members_roundtrip(meta):
    meta.add_universe_members("CN_Equity_A", ["a.SH", "b.SH"])
    assert meta.get_universe_symbols("CN_Equity_A") == ["a.SH", "b.SH"]


def test_meta_kv_timestamp(meta):
    assert meta.get_meta_ts("x") is None
    meta.set_meta_flag("x")
    assert meta.get_meta_ts("x") == pytest.approx(time.time(), abs=2)


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


def test_ex_factors_roundtrip(meta):
    meta.upsert_ex_factors("600000.SH", [(1700000000000, 0.95), (1710000000000, 0.92)])
    assert meta.get_ex_factors("600000.SH") == [(1700000000000, 0.95), (1710000000000, 0.92)]
    meta.upsert_ex_factors("600000.SH", [(1700000000000, 0.95)])  # 幂等去重
    assert len(meta.get_ex_factors("600000.SH")) == 2
    assert meta.get_ex_factors("000001.SZ") == []


def test_list_coverage_empty(meta):
    total, rows = meta.list_coverage()
    assert total == 0 and rows == []


def test_list_coverage_returns_rows(meta):
    meta.extend_coverage("600000.SH", "1d", 1000, 2000)
    meta.upsert_instruments([{"symbol": "600000.SH", "code": "600000", "name": "浦发银行"}])
    total, rows = meta.list_coverage()
    assert total == 1
    r = rows[0]
    assert r["symbol"] == "600000.SH" and r["period"] == "1d"
    assert r["start_ms"] == 1000 and r["end_ms"] == 2000
    assert r["code"] == "600000" and r["name"] == "浦发银行"


def test_list_coverage_search_and_period_filter(meta):
    meta.extend_coverage("600000.SH", "1d", 1000, 2000)
    meta.extend_coverage("000001.SZ", "1d", 1000, 2000)
    meta.extend_coverage("600000.SH", "5m", 1000, 2000)
    meta.upsert_instruments([{"symbol": "600000.SH", "code": "600000", "name": "浦发银行"}])
    total, rows = meta.list_coverage(q="600000")       # 按代码/symbol
    assert total == 2
    total, rows = meta.list_coverage(q="浦发")           # 按名称
    assert total == 2
    total, rows = meta.list_coverage(period="1d")      # 周期过滤
    assert total == 2
    total, rows = meta.list_coverage(q="nope")
    assert total == 0


def test_list_coverage_pagination(meta):
    for i, sym in enumerate(["a.SH", "b.SH", "c.SH", "d.SH"]):
        meta.extend_coverage(sym, "1d", 1000 + i, 2000 + i)
    total, rows = meta.list_coverage(page=2, size=2)
    assert total == 4 and [r["symbol"] for r in rows] == ["c.SH", "d.SH"]
