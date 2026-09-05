import pandas as pd
import pytest
import factors.factors  # noqa: F401
from factors.store import FactorStore

BAR_COLS = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]

def kdf(symbol, t0, closes, vols=None):
    n = len(closes); vols = vols or [1000 + i for i in range(n)]
    return pd.DataFrame({"symbol": [symbol]*n, "timestamp": [t0 + i for i in range(n)],
        "open": closes, "high": [c + 0.5 for c in closes], "low": [c - 0.5 for c in closes],
        "close": closes, "volume": vols})

class FakeDC:
    def __init__(self, data): self.data = data; self.calls = []
    def get_klines(self, symbol, period="1d", start_ms=None, end_ms=None, adjust="forward"):
        df = self.data.get(symbol, pd.DataFrame(columns=BAR_COLS))
        if start_ms is not None: df = df[df["timestamp"] >= start_ms]
        if end_ms is not None:   df = df[df["timestamp"] <= end_ms]
        self.calls.append((symbol, start_ms, end_ms))
        return df.copy()

CLOSES = [10 + ((i * 7) % 13) / 10 for i in range(60)]  # 非单调，波动可用

@pytest.fixture
def dc(tmp_path):
    d = FakeDC({"a.SH": kdf("a.SH", 100, CLOSES)})
    return d

def test_first_get_computes_and_persists(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    out = fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    assert len(out) == 60 and len(dc.calls) == 1
    parts = list((tmp_path / "f").rglob("part.parquet"))
    assert len(parts) == 1  # 已落盘

def test_second_get_hits_cache(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    a = fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    b = fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    assert len(dc.calls) == 1            # 二次命中，不重算
    # NaN 相等用 assert_series_equal（NaN==NaN → False，.all() 在 warmup NaN 处恒 False）
    pd.testing.assert_series_equal(a, b, check_names=False)

def test_gap_only_fetches_tail(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 120)
    out = fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    assert len(out) == 60
    assert dc.calls[0] == ("a.SH", 100, 120)   # 首查
    # 尾缺口补算带 lookback seed：ma n=5 → lookback=5 → 向前多取 5 根 K 线，
    # 取 [121-5, 159]=[116,159]；算完丢弃 seed 区（[116..120]）再合并落盘。
    assert dc.calls[1] == ("a.SH", 116, 159)
    from backtest.indicators import ma
    expect = ma(pd.Series(CLOSES), 5)          # 全窗口现算 = 已存头 + 补算尾
    # lookback seed 语义：缺口起始的 n-1 根窗口已满，不再 NaN 假空；
    # 因子值在全窗与"整段现算"等价（真实窗口头 warmup NaN 两边都有，assert_series_equal NaN-safe）。
    # out 索引=timestamp 100..159，expect 为 0..59 RangeIndex，故 check_index=False。
    pd.testing.assert_series_equal(out, expect, check_names=False, check_index=False)

def test_no_lookahead(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    out = fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    from backtest.indicators import ma
    # 值只依赖 ≤i 的数据：整段预取结果在 i 处 == 只用 [0..i] 现算
    for i in range(4, 60):
        prefix = pd.Series(CLOSES[:i + 1])
        assert out.iloc[i] == pytest.approx(ma(prefix, 5).iloc[-1])

def test_version_bump_recomputes(tmp_path, dc):
    from dataclasses import replace
    from factors.registry import REGISTRY
    fs = FactorStore(dc, root=tmp_path / "f")
    fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    orig = REGISTRY["ma"]
    try:
        REGISTRY["ma"] = replace(orig, version=2)     # 模拟定义变更（公式/口径）
        fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
        dirs = [p for p in (tmp_path / "f").iterdir() if p.is_dir()]
        assert len(dirs) == 2                          # 新指纹新目录，旧值保留
    finally:
        REGISTRY["ma"] = orig                          # 无论断言成败都还原

def test_refresh_overwrites(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    a = fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    dc.data["a.SH"]["close"] = [x + 100 for x in CLOSES]  # 底层数据变了
    b = fs.refresh("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    assert (a.iloc[20:] != b.iloc[20:]).any()      # 跳过 warmup NaN，值确实刷新

def test_drop_removes_dir(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    fs.drop("ma", {"n": 5})
    assert not list((tmp_path / "f").rglob("part.parquet"))

def test_list_stored_and_load_stored(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)      # 落盘 ma n=5
    fs.get("a.SH", "ma", {"n": 20}, "1d", 100, 159)     # 另一指纹 ma n=20
    dirs = fs.list_stored()
    assert len(dirs) == 2
    d = next(x for x in dirs if x["params"] == {"n": 5})
    assert d["name"] == "ma" and d["version"] == 1 and d["adjust"] == "forward"
    assert d["cells"] == [{"symbol": "a.SH", "period": "1d", "rows": 60}]
    assert d["total_rows"] == 60
    s = fs.load_stored(d["fingerprint"], "a.SH", "1d")
    assert len(s) == 60 and s.index[0] == 100


def test_list_stored_and_load_stored_missing(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    assert fs.list_stored() == []
    assert fs.load_stored("deadbeef", "a.SH", "1d").empty
