"""事件驱动策略接口：Strategy 基类 + Context。

时序约定（由 engine 驱动）：
- `init(ctx)` 回测开始前调用一次（可用全量历史预计算指标）
- `on_bar(ctx)` 每个时间点调用一次；ctx.bars 是**当前 bar**，ctx.history 是**截至当前 bar 的已收盘历史**
- 下单在下一根 bar 开盘撮合（无前视）
"""

from backtest.broker import Broker, Order


class Strategy:
    """策略基类。子类实现 init/on_bar/on_finish。"""

    def init(self, ctx) -> None: ...
    def on_bar(self, ctx) -> None: ...
    def on_finish(self, ctx) -> None: ...


class Context:
    """策略上下文：资金/持仓/下单/历史。只读访问 + 下单，不直接改账户。"""

    def __init__(self, broker: Broker, symbols: list[str],
                 history_fn, bars_fn, now_fn):
        self._broker = broker
        self._symbols = list(symbols)
        self._history = history_fn   # (symbol) -> 截至当前 bar 的前复权 df
        self._bars = bars_fn         # () -> {symbol: bar dict}
        self._now = now_fn           # () -> 当前 bar 时间戳

    @property
    def symbols(self) -> list[str]:
        return self._symbols

    @property
    def cash(self) -> float:
        return self._broker.cash

    @property
    def positions(self) -> dict[str, int]:
        return dict(self._broker.positions)

    @property
    def bars(self) -> dict:
        return self._bars()

    @property
    def now(self) -> int:
        return self._now()

    @property
    def trades(self):
        return self._broker.trades

    def _resolve(self, symbol):
        return symbol or (self._symbols[0] if self._symbols else None)

    def history(self, symbol=None):
        return self._history(self._resolve(symbol))

    def buy(self, symbol=None, shares=None) -> Order:
        return self._broker.submit(Order(self._resolve(symbol), "buy", shares))

    def sell(self, symbol=None, shares=None) -> Order:
        return self._broker.submit(Order(self._resolve(symbol), "sell", shares))

    def close_position(self, symbol=None) -> Order:
        return self._broker.submit(Order(self._resolve(symbol), "sell", None))
