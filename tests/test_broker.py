"""撮合/账户测试：次bar开盘成交、成本、一手取整、T+1、涨跌停顺延。"""
import pytest

from backtest.broker import Broker, Order


def _bar(open_, high=None, low=None, close=None, volume=0):
    # 默认非一字板（high/low 与 open 不同），一字板需显式传 open==high==low
    high = open_ * 1.01 if high is None else high
    low = open_ * 0.99 if low is None else low
    close = open_ if close is None else close
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume}


def test_buy_fills_at_next_bar_open():
    b = Broker(initial_cash=100_000)
    b.submit(Order("a.SH", "buy", shares=100))
    b.execute_pending({"a.SH": _bar(10.0)}, ts=1)
    assert b.positions["a.SH"] == 100
    # 1000 成交 + 最低佣金 5 元
    assert b.cash == pytest.approx(100_000 - 1000 - 5)


def test_commission_pct_and_min():
    b = Broker(initial_cash=10_000_000)
    b.submit(Order("a.SH", "buy", shares=100_000))  # 100_000*10 = 1_000_000
    b.execute_pending({"a.SH": _bar(10.0)}, ts=1)
    assert b.trades[0].commission == pytest.approx(1_000_000 * 0.0003)
    b2 = Broker(initial_cash=100_000)
    b2.submit(Order("a.SH", "buy", shares=100))  # 1000*0.0003=0.3 < 5
    b2.execute_pending({"a.SH": _bar(10.0)}, ts=1)
    assert b2.trades[0].commission == 5.0  # 最低佣金


def test_stamp_tax_on_sell():
    b = Broker(initial_cash=100_000)
    b.submit(Order("a.SH", "buy", shares=1000))
    b.execute_pending({"a.SH": _bar(10.0)}, ts=1)
    b.end_of_bar()
    b.submit(Order("a.SH", "sell", shares=1000))
    b.execute_pending({"a.SH": _bar(11.0)}, ts=2)
    sell = b.trades[-1]
    assert sell.side == "sell"
    assert sell.tax == pytest.approx(1000 * 11.0 * 0.0005)  # 卖出印花税


def test_slippage_affects_fill_price():
    b = Broker(initial_cash=100_000, slippage=0.01)
    b.submit(Order("a.SH", "buy", shares=100))
    b.execute_pending({"a.SH": _bar(10.0)}, ts=1)
    assert b.trades[0].price == pytest.approx(10.0 * 1.01)
    b.submit(Order("a.SH", "sell", shares=100))
    b.execute_pending({"a.SH": _bar(11.0)}, ts=2)
    assert b.trades[-1].price == pytest.approx(11.0 * 0.99)


def test_lot_size_rounding_full_buy():
    b = Broker(initial_cash=100_000)
    b.submit(Order("a.SH", "buy", shares=None))  # 全仓
    b.execute_pending({"a.SH": _bar(10.0)}, ts=1)
    assert b.positions["a.SH"] % 100 == 0
    assert b.positions["a.SH"] > 0
    # 预算 10 万，10000 股成本 100030 超支 -> 9900 股（含佣金）
    assert b.positions["a.SH"] == 9900


def test_cash_insufficient_dropped():
    b = Broker(initial_cash=500)  # 一手（100 股 × 10 元）都买不起
    b.submit(Order("a.SH", "buy", shares=None))
    b.execute_pending({"a.SH": _bar(10.0)}, ts=1)
    assert "a.SH" not in b.positions  # 放弃


def test_t_plus_1_blocks_same_bar_sell():
    b = Broker(initial_cash=100_000)
    b.submit(Order("a.SH", "buy", shares=1000))
    b.execute_pending({"a.SH": _bar(10.0)}, ts=1)  # bar1 开盘买入
    b.submit(Order("a.SH", "sell", shares=1000))
    b.execute_pending({"a.SH": _bar(11.0)}, ts=1)  # 同 bar1 卖出被锁
    assert b.positions["a.SH"] == 1000  # 卖不出


def test_t_plus_1_allows_next_bar_sell():
    b = Broker(initial_cash=100_000)
    b.submit(Order("a.SH", "buy", shares=1000))
    b.execute_pending({"a.SH": _bar(10.0)}, ts=1)
    b.end_of_bar()  # bar1 结束，次日解锁
    b.submit(Order("a.SH", "sell", shares=1000))
    b.execute_pending({"a.SH": _bar(9.0)}, ts=2)  # bar2 可卖
    assert b.positions.get("a.SH", 0) == 0  # 清仓后 key 移除


def test_limit_board_order_held():
    b = Broker(initial_cash=100_000)
    b.submit(Order("a.SH", "buy", shares=1000))
    b.execute_pending({"a.SH": _bar(10.0, 10.0, 10.0)}, ts=1)  # 一字板 open==high==low
    assert b.positions.get("a.SH", 0) == 0  # 未成交，订单顺延
    assert b._pending  # 仍挂单
    b.execute_pending({"a.SH": _bar(10.5, 11.0, 10.2)}, ts=2)  # 次日打开
    assert b.positions["a.SH"] == 1000


def test_sell_none_closes_position():
    b = Broker(initial_cash=100_000)
    b.submit(Order("a.SH", "buy", shares=500))
    b.execute_pending({"a.SH": _bar(10.0)}, ts=1)
    b.end_of_bar()
    b.submit(Order("a.SH", "sell", shares=None))  # 清仓
    b.execute_pending({"a.SH": _bar(12.0)}, ts=2)
    assert b.positions.get("a.SH", 0) == 0  # 清仓后 key 移除
