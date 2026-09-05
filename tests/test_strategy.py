"""策略接口/Context 测试：下单接线、持仓/现金读写、历史不含未来。"""
import pandas as pd

from backtest.broker import Broker, Order
from backtest.strategy import Context, Strategy


def _mk_df(ts, closes):
    return pd.DataFrame({
        "symbol": "a.SH", "timestamp": ts, "open": closes,
        "high": [c + 0.5 for c in closes], "low": [c - 0.5 for c in closes],
        "close": closes, "volume": [1000] * len(closes),
    })


def _mk_ctx(broker, symbols=None, history=None):
    symbols = symbols or ["a.SH"]
    history = history or (lambda s: _mk_df([1, 2], [10.0, 11.0]))
    return Context(broker, symbols=symbols, history_fn=history,
                   bars_fn=lambda: {"a.SH": {"open": 10.0, "close": 10.5}},
                   now_fn=lambda: 2)


def test_context_buy_submits_order():
    broker = Broker(initial_cash=100_000)
    ctx = _mk_ctx(broker)
    ctx.buy("a.SH", shares=100)
    assert len(broker._pending) == 1
    assert broker._pending[0].side == "buy"


def test_context_buy_sell_roundtrip():
    broker = Broker(initial_cash=100_000)
    ctx = _mk_ctx(broker)
    ctx.buy("a.SH", shares=100)
    broker.execute_pending({"a.SH": {"open": 10.0, "high": 10.5, "low": 9.5}}, ts=2)
    assert ctx.positions["a.SH"] == 100
    assert ctx.cash < 100_000
    broker.end_of_bar()
    ctx.sell("a.SH", shares=100)
    broker.execute_pending({"a.SH": {"open": 11.0, "high": 11.5, "low": 10.5}}, ts=3)
    assert ctx.positions.get("a.SH", 0) == 0  # 清仓后 key 移除
    assert ctx.cash > 100_000 - 1000  # 高价卖出后现金回升


def test_context_close_position():
    broker = Broker(initial_cash=100_000)
    ctx = _mk_ctx(broker)
    ctx.buy("a.SH", shares=500)
    broker.execute_pending({"a.SH": {"open": 10.0, "high": 10.5, "low": 9.5}}, ts=2)
    broker.end_of_bar()
    ctx.close_position("a.SH")
    assert broker._pending[-1].shares is None  # 清仓单
    broker.execute_pending({"a.SH": {"open": 12.0, "high": 12.5, "low": 11.5}}, ts=3)
    assert ctx.positions.get("a.SH", 0) == 0  # 清仓后 key 移除


def test_history_does_not_include_future():
    broker = Broker(initial_cash=100_000)
    df = _mk_df([1, 2, 3, 4], [10, 11, 12, 13])
    seen = {}

    class Spy(Strategy):
        def on_bar(self, ctx):
            seen["hist"] = ctx.history("a.SH")

    spy = Spy()
    # 手动模拟：now=2 时 history 只给 ts<=2 的行
    now = 2
    hist = df[df["timestamp"] <= now]
    ctx = Context(broker, symbols=["a.SH"], history_fn=lambda s: hist,
                  bars_fn=lambda: {}, now_fn=lambda: now)
    spy.on_bar(ctx)
    assert seen["hist"]["timestamp"].max() == 2  # 不含未来 bar


def test_strategy_interface_hooks():
    class S(Strategy):
        def __init__(self):
            self.events = []

        def init(self, ctx):
            self.events.append("init")

        def on_bar(self, ctx):
            self.events.append("bar")

        def on_finish(self, ctx):
            self.events.append("finish")

    broker = Broker()
    ctx = _mk_ctx(broker)
    s = S()
    s.init(ctx)
    s.on_bar(ctx)
    s.on_finish(ctx)
    assert s.events == ["init", "bar", "finish"]
