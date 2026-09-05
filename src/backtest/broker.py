"""撮合与账户：次bar开盘成交、交易成本、T+1 锁定、涨跌停顺延。

时序约定（由 engine 驱动）：
- `submit(order)` 下单挂起，`execute_pending(bars, ts)` 在**下一根 bar** 的开盘价撮合
- `end_of_bar()` 在每根 bar 的 on_bar 之后调用：T+1 锁定解除（当日买入次日可卖）
"""

from dataclasses import dataclass


@dataclass
class Order:
    symbol: str
    side: str                     # "buy" / "sell"
    shares: int | None = None     # None = 全仓买入 / 全部清仓
    status: str = "pending"


@dataclass
class Trade:
    symbol: str
    side: str
    shares: int
    price: float
    commission: float
    tax: float
    ts: int


class Broker:
    def __init__(self, initial_cash: float = 1_000_000,
                 commission: float = 0.0003, min_commission: float = 5.0,
                 stamp_tax: float = 0.0005, slippage: float = 0.0,
                 lot_size: int = 100, t_plus_1: bool = True):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission = commission          # 佣金率（双边）
        self.min_commission = min_commission  # 最低佣金（元）
        self.stamp_tax = stamp_tax            # 印花税（卖出）
        self.slippage = slippage              # 滑点比例
        self.lot_size = lot_size              # A 股一手股数
        self.t_plus_1 = t_plus_1
        self.positions: dict[str, int] = {}
        self._bought_at: dict[str, tuple[int, int]] = {}  # {symbol: (买入bar ts, 股数)}
        self._pending: list[Order] = []
        self.trades: list[Trade] = []

    # ---- 下单（挂起，次bar开盘撮合）----
    def submit(self, order: Order) -> Order:
        self._pending.append(order)
        return order

    # ---- 撮合 ----
    def execute_pending(self, bars: dict, ts: int) -> None:
        remaining: list[Order] = []
        for order in self._pending:
            bar = bars.get(order.symbol)
            if bar is None:
                remaining.append(order)
                continue
            if self._is_limit_board(bar):
                remaining.append(order)  # 一字板：无法成交，顺延下一bar
                continue
            if order.side == "buy":
                price = bar["open"] * (1 + self.slippage)
                if not self._fill_buy(order, price, ts):
                    remaining.append(order)  # 现金不足且降满仓后仍买不起 -> 保留？直接放弃
            else:
                price = bar["open"] * (1 - self.slippage)
                self._fill_sell(order, price, ts)
        self._pending = remaining

    @staticmethod
    def _is_limit_board(bar) -> bool:
        o, h, l = bar["open"], bar["high"], bar["low"]
        return abs(o - h) < 1e-9 and abs(o - l) < 1e-9

    def _fill_buy(self, order: Order, price: float, ts: int) -> bool:
        shares = order.shares
        if shares is None:
            shares = self._max_buyable(price)
        else:
            # 指定股数现金不足 -> 降为满仓可买
            if price * shares + max(price * shares * self.commission, self.min_commission) > self.cash:
                shares = self._max_buyable(price)
        if shares <= 0:
            return False
        cost = shares * price
        fee = max(cost * self.commission, self.min_commission)
        if cost + fee > self.cash:
            return False
        self.cash -= cost + fee
        self.positions[order.symbol] = self.positions.get(order.symbol, 0) + shares
        prev = self._bought_at.get(order.symbol)
        if prev is not None and prev[0] == ts:
            self._bought_at[order.symbol] = (ts, prev[1] + shares)
        else:
            self._bought_at[order.symbol] = (ts, shares)
        order.status = "filled"
        self.trades.append(Trade(order.symbol, "buy", shares, price, fee, 0.0, ts))
        return True

    def _fill_sell(self, order: Order, price: float, ts: int) -> None:
        held = self.positions.get(order.symbol, 0)
        if held <= 0:
            order.status = "cancelled"
            return
        bought_ts, bought_shares = self._bought_at.get(order.symbol, (None, 0))
        locked = bought_shares if (self.t_plus_1 and bought_ts == ts) else 0
        sellable = held - locked
        if sellable <= 0:
            return  # 当日买入不可卖 -> 废单
        shares = sellable if order.shares is None else min(order.shares, sellable)
        proceeds = shares * price
        fee = max(proceeds * self.commission, self.min_commission)
        tax = proceeds * self.stamp_tax
        self.cash += proceeds - fee - tax
        self.positions[order.symbol] = held - shares
        order.status = "filled"
        self.trades.append(Trade(order.symbol, "sell", shares, price, fee, tax, ts))
        if self.positions[order.symbol] == 0:
            # 清仓后移除 key：positions 只含正持仓，"symbol in positions" = 仍持有
            self.positions.pop(order.symbol, None)
            self._bought_at.pop(order.symbol, None)

    def _max_buyable(self, price: float) -> int:
        """按当前现金可买的最大手数（含佣金），返回一手取整股数。"""
        if price <= 0:
            return 0
        lot = self.lot_size
        max_shares = int(self.cash // price // lot) * lot
        while max_shares > 0:
            cost = max_shares * price
            fee = max(cost * self.commission, self.min_commission)
            if cost + fee <= self.cash:
                return max_shares
            max_shares -= lot
        return 0

    def end_of_bar(self) -> None:
        """bar 结束：T+1 锁定解除（当日买入次日可卖）。"""
        self._bought_at.clear()
