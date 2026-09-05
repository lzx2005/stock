"""回测引擎测试：时间并集对齐、无前视撮合时序、共享资金池、生命周期。"""
import pandas as pd
import pytest

from backtest.broker import Broker
from backtest.engine import BacktestEngine
from backtest.strategy import Strategy

BAR_COLS = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]


def kdf(symbol, t0, closes, opens=None):
    """合成 K 线：ts = t0, t0+1, ...；high/low 与 close 拉开（非一字板）。"""
    n = len(closes)
    opens = closes if opens is None else opens
    return pd.DataFrame({
        "symbol": [symbol] * n,
        "timestamp": [t0 + i for i in range(n)],
        "open": opens,
        "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes],
        "close": closes,
        "volume": [1000] * n,
    })


class FakeDC:
    """鸭子类型 DataCenter：get_klines 返回预设 df（含 start/end 裁剪）。"""

    def __init__(self, data):
        self.data = data

    def get_klines(self, symbol, period="1d", start_ms=None, end_ms=None, adjust="forward"):
        df = self.data.get(symbol, pd.DataFrame(columns=BAR_COLS))
        if start_ms is not None:
            df = df[df["timestamp"] >= start_ms]
        if end_ms is not None:
            df = df[df["timestamp"] <= end_ms]
        return df.copy()


def test_union_times_and_bar_visibility():
    a = kdf("a.SH", 100, [10, 11, 12])        # ts 100,101,102
    b = kdf("b.SH", 101, [20, 21, 22, 23])    # ts 101,102,103,104
    eng = BacktestEngine(FakeDC({"a.SH": a, "b.SH": b}), ["a.SH", "b.SH"])
    assert eng.times == [100, 101, 102, 103, 104]

    seen = []

    class Spy(Strategy):
        def on_bar(self, ctx):
            seen.append((ctx.now, sorted(ctx.bars), len(ctx.history("a.SH")),
                         len(ctx.history("b.SH"))))

    eng.run(Spy())
    assert seen[0] == (100, ["a.SH"], 1, 0)    # t=100 只有 a，且 history 含当前 bar
    assert seen[1] == (101, ["a.SH", "b.SH"], 2, 1)
    assert seen[-1] == (104, ["b.SH"], 3, 4)   # a 停牌后 history 仍含其全部既往 bar


def test_init_sees_full_history():
    df = kdf("a.SH", 1, [10, 11, 12, 13])
    got = {}

    class S(Strategy):
        def init(self, ctx):
            got["n"] = len(ctx.history("a.SH"))

        def on_bar(self, ctx):
            pass

    eng = BacktestEngine(FakeDC({"a.SH": df}), ["a.SH"])
    eng.run(S())
    assert got["n"] == 4  # init 预计算指标需要全量


def test_history_never_includes_future():
    df = kdf("a.SH", 1, [10, 11, 12, 13, 14])
    hist_max = []

    class Spy(Strategy):
        def on_bar(self, ctx):
            hist_max.append(ctx.history("a.SH")["timestamp"].max())

    eng = BacktestEngine(FakeDC({"a.SH": df}), ["a.SH"])
    eng.run(Spy())
    assert hist_max == [1, 2, 3, 4, 5]  # 逐 bar 前进，从不出现未来时间戳


def test_buy_fills_at_next_bar_open():
    df = kdf("a.SH", 1, [10.0, 10.5, 11.0], opens=[9.9, 10.0, 10.1])

    class BuyOnce(Strategy):
        def __init__(self):
            self.fired = False

        def on_bar(self, ctx):
            if not self.fired:
                ctx.buy("a.SH", shares=100)
                self.fired = True

    eng = BacktestEngine(FakeDC({"a.SH": df}), ["a.SH"])
    eng.run(BuyOnce())
    # t=1 提交 -> t=2 开盘 10.0 成交（不是 t=1 的 9.9）
    assert eng.broker.positions["a.SH"] == 100
    assert eng.broker.trades[0].ts == 2
    assert eng.broker.trades[0].price == 10.0


def test_shared_cash_across_symbols():
    a = kdf("a.SH", 1, [100.0, 100.0])
    b = kdf("b.SH", 1, [100.0, 100.0])

    class BuyBoth(Strategy):
        def on_bar(self, ctx):
            if ctx.now == 1:
                ctx.buy("a.SH", shares=100)
                ctx.buy("b.SH", shares=100)

    eng = BacktestEngine(FakeDC({"a.SH": a, "b.SH": b}), ["a.SH", "b.SH"],
                         initial_cash=15_000)
    eng.run(BuyBoth())
    # a 占 10005（含最低佣金 5），余 4995 买不起一手 b -> b 放弃
    assert eng.broker.positions["a.SH"] == 100
    assert eng.broker.positions.get("b.SH", 0) == 0


def test_buy_sell_full_cycle():
    closes = [10, 10, 11, 12, 13, 14, 13, 12, 11, 10]
    df = kdf("a.SH", 1, closes)

    class Signal(Strategy):
        def on_bar(self, ctx):
            c = ctx.bars["a.SH"]["close"]
            if c >= 12 and "a.SH" not in ctx.positions:
                ctx.buy("a.SH", shares=None)      # t=4 信号
            elif c < 12 and "a.SH" in ctx.positions:
                ctx.sell("a.SH")                  # t=9 信号

    eng = BacktestEngine(FakeDC({"a.SH": df}), ["a.SH"])
    eng.run(Signal())
    trades = eng.broker.trades
    assert [t.side for t in trades] == ["buy", "sell"]
    # t=5 开盘 = closes[4]=13，t=10 开盘 = closes[9]=10（open 默认=closes）
    assert trades[0].ts == 5 and trades[0].price == closes[4]
    assert trades[1].ts == 10 and trades[1].price == closes[9]
    assert eng.broker.positions == {}
    assert eng.broker.cash > 0


def test_lifecycle_init_bar_finish():
    df = kdf("a.SH", 1, [10, 10])
    events = []

    class S(Strategy):
        def init(self, ctx):
            events.append("init")

        def on_bar(self, ctx):
            events.append("bar")

        def on_finish(self, ctx):
            events.append("finish")

    eng = BacktestEngine(FakeDC({"a.SH": df}), ["a.SH"])
    eng.run(S())
    assert events == ["init", "bar", "bar", "finish"]


def test_no_data_runs_without_crash():
    eng = BacktestEngine(FakeDC({}), ["a.SH"])
    broker = eng.run(Strategy())
    assert broker is not None
    assert eng.times == []
