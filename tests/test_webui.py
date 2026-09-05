import pandas as pd
import pytest
from fastapi.testclient import TestClient

from datacenter.store.klines import KlineStore
from datacenter.store.meta import MetaStore
import factors.factors  # noqa: F401 —— 显式注册内置因子（_seed 里 get("ma") 需要）
from factors.store import FactorStore
from tests.conftest import make_kline_df
from webui.app import create_app

DAY = 86_400_000
T0 = 1754011800000  # 2025-08-01 09:30 Asia/Shanghai = 1754011800000 ms


class FakeDC:
    """只读假数据中心：get_klines 按范围切分合成数据（仅供 FactorStore.get 计算落盘）。"""
    def __init__(self, data):
        self.data = data
    def get_klines(self, symbol, period="1d", start_ms=None, end_ms=None, adjust="forward"):
        df = self.data.get(symbol, pd.DataFrame())
        if start_ms is not None:
            df = df[df["timestamp"] >= start_ms]
        if end_ms is not None:
            df = df[df["timestamp"] <= end_ms]
        return df.copy()


def _seed(tmp_path):
    """构造一个临时 data 目录：1 标的日线 10 根 + 覆盖记录 + 1 个已算因子(ma n=5)。"""
    data_dir = tmp_path / "data"
    (data_dir / "klines").mkdir(parents=True, exist_ok=True)
    kstore = KlineStore(data_dir / "klines")
    meta = MetaStore(data_dir / "meta.db")
    df = make_kline_df("600000.SH", T0, 10, DAY)
    kstore.write(df, "1d", tag="t")
    meta.extend_coverage("600000.SH", "1d", T0, T0 + 9 * DAY)
    meta.upsert_instruments([{"symbol": "600000.SH", "code": "600000", "name": "浦发银行"}])
    fs = FactorStore(FakeDC({"600000.SH": df}), root=data_dir / "factors")
    fs.get("600000.SH", "ma", {"n": 5}, "1d", T0, T0 + 9 * DAY)
    return data_dir


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(data_dir=_seed(tmp_path)))


def test_periods(client):
    r = client.get("/api/periods")
    assert r.status_code == 200
    assert "1d" in r.json()["items"]


def test_coverage_search_and_pagination(client):
    r = client.get("/api/coverage", params={"q": "600000"})
    body = r.json()
    assert body["total"] == 1 and body["items"][0]["symbol"] == "600000.SH"
    assert body["items"][0]["name"] == "浦发银行"
    assert client.get("/api/coverage", params={"q": "nope"}).json()["total"] == 0


def test_klines_paginated_and_default_range(client):
    r = client.get("/api/klines", params={"symbol": "600000.SH", "period": "1d", "page": 1, "size": 4})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 10 and len(body["rows"]) == 4
    assert body["rows"][0][0] == T0 and len(body["rows"][0]) == 7


def test_klines_bad_period_404(client):
    assert client.get("/api/klines", params={"symbol": "600000.SH", "period": "1x"}).status_code == 404


def test_klines_unknown_symbol_total_zero(client):
    body = client.get("/api/klines", params={"symbol": "NO.SH", "period": "1d"}).json()
    assert body["total"] == 0


def test_factors_registered_and_searchable(client):
    body = client.get("/api/factors", params={"q": "ma"}).json()
    assert body["total"] >= 1
    assert all("ma" in i["name"] for i in body["items"])
    assert any(i["stored_dir_count"] == 1 for i in body["items"] if i["name"] == "ma")


def test_factor_dirs_lists_cells(client):
    body = client.get("/api/factor-dirs").json()
    assert body["total"] == 1
    d = body["items"][0]
    assert d["name"] == "ma"
    assert d["cells"] == [{"symbol": "600000.SH", "period": "1d", "rows": 10}]
    assert d["total_rows"] == 10


def test_factor_values_paginated_and_404(client):
    fp = client.get("/api/factor-dirs").json()["items"][0]["fingerprint"]
    body = client.get("/api/factor-values",
                      params={"fingerprint": fp, "symbol": "600000.SH", "period": "1d", "size": 5}).json()
    assert body["total"] == 10 and len(body["rows"]) == 5
    assert client.get("/api/factor-values",
                      params={"fingerprint": "deadbeef", "symbol": "x", "period": "1d"}).status_code == 404
