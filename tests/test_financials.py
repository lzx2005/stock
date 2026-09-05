import pandas as pd
import pytest

from datacenter import DataCenter
from tests.conftest import FakeTickFlow

INCOME_ROWS = [
    {"period_end": "2024-12-31", "revenue": 1e9, "net_income": 2e8},
    {"period_end": "2025-03-31", "revenue": 3e8, "net_income": 5e7},
]


class FakeFinancials:
    def __init__(self):
        self.calls = []

    def income(self, symbols, latest=False, as_dataframe=False):
        self.calls.append(dict(symbols=symbols, latest=latest))
        rows = [{**r, "symbol": s} for s in symbols for r in INCOME_ROWS]
        return pd.DataFrame(rows) if as_dataframe else rows


@pytest.fixture
def dc(tmp_path):
    fake = FakeTickFlow(symbols=["600000.SH"])
    fake.financials = FakeFinancials()
    return DataCenter(data_dir=tmp_path / "data", client_tf=fake), fake


def test_income_cached_after_first_fetch(dc):
    dc_, fake = dc
    df1 = dc_.get_financials("income", ["600000.SH"])
    df2 = dc_.get_financials("income", ["600000.SH"])
    assert len(df1) == 2 and len(df2) == 2
    assert len(fake.financials.calls) == 1  # 第二次走缓存


def test_latest_uses_cache_within_ttl(dc):
    dc_, fake = dc
    dc_.get_financials("income", ["600000.SH"], latest=True)
    dc_.get_financials("income", ["600000.SH"], latest=True)
    assert len(fake.financials.calls) == 1


def test_dedup_on_refetch(dc):
    dc_, fake = dc
    dc_.get_financials("income", ["600000.SH"])
    dc_.refresh_financials("income", ["600000.SH"])  # 强制刷新
    df = dc_.get_financials("income", ["600000.SH"])
    assert len(df) == 2  # 重复拉取不产生重复行
