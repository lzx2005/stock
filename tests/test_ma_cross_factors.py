import pandas as pd
import factors.factors  # noqa: F401  —— import 即注册内置因子
from backtest.engine import BacktestEngine
from backtest.performance import analyze
from examples.strategies.ma_cross import MaCross
from factors.store import FactorStore

def kdf_with_crosses(symbol="a.SH", n=60):
    # 构造出现金叉/死叉的价格序列（正弦趋势 + 噪声），确保有交易
    import math
    closes = [round(10 + 3 * math.sin(i / 4.0) + (i % 7) * 0.1, 3) for i in range(n)]
    df = pd.DataFrame({"symbol": [symbol]*n, "timestamp": list(range(100, 100 + n)),
        "open": closes, "high": [c + 0.5 for c in closes], "low": [c - 0.5 for c in closes],
        "close": closes, "volume": [1000 + i for i in range(n)]})
    return df

class FakeDC:
    def __init__(self, df): self.df = df
    def get_klines(self, symbol, period="1d", start_ms=None, end_ms=None, adjust="forward"):
        d = self.df
        if start_ms is not None: d = d[d["timestamp"] >= start_ms]
        if end_ms is not None:   d = d[d["timestamp"] <= end_ms]
        return d.copy()

def _run(df, ma_cross):
    eng = BacktestEngine(FakeDC(df), ["a.SH"], period="1d",
                         start_ms=100, end_ms=100 + len(df) - 1)
    eng.run(ma_cross)
    return analyze(eng.broker, eng.data, period="1d")

def test_golden_factors_identical(tmp_path):
    df = kdf_with_crosses()
    orig = _run(df, MaCross(5, 20))                     # 现算版（原逻辑）
    refa = _run(df, MaCross(5, 20, fs=FactorStore(FakeDC(df), root=tmp_path / "f")))
    # 逐笔交易一致（时间/价格/股数/盈亏）
    assert [(t.buy_ts, t.sell_ts, t.shares, round(t.pnl, 2)) for t in orig.trades] == \
           [(t.buy_ts, t.sell_ts, t.shares, round(t.pnl, 2)) for t in refa.trades]
    # 总收益一致
    assert round(orig.total_return, 6) == round(refa.total_return, 6)
    # 二次运行命中缓存仍一致（复用路径）
    refb = _run(df, MaCross(5, 20, fs=FactorStore(FakeDC(df), root=tmp_path / "f")))
    assert refb.trade_count == refa.trade_count
