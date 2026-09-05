"""绩效统计测试：权益曲线（close 重估）+ 收益/回撤/夏普/胜率/盈亏比，手算对拍。"""
import math

import pandas as pd
import pytest

from backtest.broker import Broker, Trade
from backtest.performance import analyze, equity_curve


def closes_df(symbol, ts, closes):
    return pd.DataFrame({
        "symbol": symbol, "timestamp": ts, "open": closes,
        "high": [c + 1 for c in closes], "low": [c - 1 for c in closes],
        "close": closes, "volume": [1000] * len(ts),
    })


def _sample():
    """a.SH 买10@ts2 卖12@ts3（+200）；b.SH 买20@ts4 卖18@ts5（-200）。"""
    trades = [
        Trade("a.SH", "buy", 100, 10.0, 5.0, 0.0, 2),
        Trade("a.SH", "sell", 100, 12.0, 5.0, 0.6, 3),
        Trade("b.SH", "buy", 100, 20.0, 5.0, 0.0, 4),
        Trade("b.SH", "sell", 100, 18.0, 5.0, 0.9, 5),
    ]
    data = {
        "a.SH": closes_df("a.SH", [1, 2, 3], [10, 12, 12]),
        "b.SH": closes_df("b.SH", [1, 2, 3, 4, 5], [20, 20, 20, 20, 18]),
    }
    broker = Broker(initial_cash=100_000)
    broker.trades = trades
    broker.cash = 100_000 - 1000 - 5 + 1200 - 5 - 0.6 - 2000 - 5 + 1800 - 5 - 0.9
    broker.positions = {}
    return broker, data


def test_equity_curve_close_valuation():
    broker, data = _sample()
    curve = equity_curve(broker, data)
    assert list(curve["timestamp"]) == [1, 2, 3, 4, 5]
    # t=2：a 买 @10 已成交，100 股按 t=2 收盘 12 重估
    assert curve["equity"].iloc[0] == pytest.approx(100_000)
    assert curve["equity"].iloc[1] == pytest.approx(98_995 + 100 * 12)
    assert curve["equity"].iloc[-1] == pytest.approx(broker.cash)  # 全部平仓 -> 等于现金


def test_analyze_metrics():
    broker, data = _sample()
    r = analyze(broker, data)
    assert r.trade_count == 2
    assert r.win_rate == pytest.approx(0.5)
    assert r.profit_loss_ratio == pytest.approx(1.0)   # 200 / 200
    assert r.final_equity == pytest.approx(99_978.5)
    assert r.total_return == pytest.approx(99_978.5 / 100_000 - 1)
    # 最大回撤：峰 100195（t=2）→ 谷 99978.5（t=5）
    assert r.max_drawdown == pytest.approx((100_195 - 99_978.5) / 100_195, rel=1e-3)
    assert math.isfinite(r.annual_return)
    assert math.isfinite(r.sharpe)
    # 交易明细：a 是盈利单，b 是亏损单
    assert [t.pnl for t in r.trades] == pytest.approx([200.0, -200.0])
    assert r.trades[0].symbol == "a.SH" and r.trades[0].buy_price == 10.0


def test_analyze_no_trades():
    broker = Broker(initial_cash=50_000)
    data = {"a.SH": closes_df("a.SH", [1, 2], [10, 10])}
    r = analyze(broker, data)
    assert r.trade_count == 0
    assert r.total_return == pytest.approx(0.0)
    assert r.max_drawdown == pytest.approx(0.0)
    assert r.win_rate == pytest.approx(0.0)
    assert r.final_equity == pytest.approx(50_000)
    assert len(equity_curve(broker, data)) == 2


def test_sharpe_positive_when_strictly_up():
    # 单调上涨 -> 夏普 > 0；年化按 252 bar/年
    trades = [Trade("a.SH", "buy", 100, 10.0, 5.0, 0.0, 2),
              Trade("a.SH", "sell", 100, 13.0, 5.0, 0.65, 3)]
    broker = Broker(initial_cash=100_000)
    broker.trades = trades
    broker.cash = 100_000 - 1000 - 5 + 1300 - 5 - 0.65
    broker.positions = {}
    data = {"a.SH": closes_df("a.SH", [1, 2, 3], [10, 13, 13])}
    r = analyze(broker, data)
    assert r.win_rate == 1.0
    assert r.sharpe > 0
    assert r.total_return > 0
