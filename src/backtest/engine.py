"""回测引擎：多标的共享账户，逐 bar 事件循环，无前视撮合时序。

时序（每根 bar）：
1. `execute_pending(bars)` —— 挂单按本 bar 开盘价撮合（上根 bar 产生的信号）
2. `strategy.on_bar(ctx)` —— 用本 bar 收盘信息下单，t+1 开盘执行
3. `end_of_bar()` —— T+1 锁定解除（当日买入次日可卖）

无前视保证：
- 信号在 t 时刻产生，成交价是 t+1 的开盘价（下单与撮合不在同一 bar）
- `ctx.history(symbol)` 只含 timestamp ≤ 当前 bar 的行；`ctx.bars` 只含当前 bar 在交易的标的
- `init(ctx)` 阶段 history 返回全量（供预计算指标）
"""

from bisect import bisect_right

import pandas as pd

from backtest.broker import Broker
from backtest.strategy import Context

EMPTY_COLS = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]


class BacktestEngine:
    def __init__(self, dc, symbols: list[str], period: str = "1d",
                 start_ms: int | None = None, end_ms: int | None = None,
                 initial_cash: float = 1_000_000.0, adjust: str = "forward",
                 broker: Broker | None = None):
        self.dc = dc
        self.symbols = list(symbols)
        self.period = period
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.adjust = adjust
        self.broker = broker or Broker(initial_cash=initial_cash)
        self._prefetch()

    # ---- 数据预取：每标的一张前复权 df + 时间戳索引 ----
    def _prefetch(self) -> None:
        self.data: dict[str, pd.DataFrame] = {}  # 公开：绩效/权益曲线复用
        self._ts: dict[str, list[int]] = {}
        self._pos: dict[str, dict[int, int]] = {}
        for s in self.symbols:
            df = self.dc.get_klines(s, self.period, self.start_ms, self.end_ms,
                                    adjust=self.adjust)
            if df.empty:
                continue
            df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
            self.data[s] = df
            self._ts[s] = df["timestamp"].tolist()
            self._pos[s] = {ts: i for i, ts in enumerate(self._ts[s])}
        union: set[int] = set()
        for ts in self._ts.values():
            union.update(ts)
        self.times: list[int] = sorted(union)

    def _history(self, symbol: str) -> pd.DataFrame:
        """截至当前 bar 的历史（不含未来）。init 阶段（self._t is None）返回全量。"""
        if symbol not in self.data:
            return pd.DataFrame(columns=EMPTY_COLS)
        if self._t is None:
            return self.data[symbol]
        n = bisect_right(self._ts[symbol], self._t)
        return self.data[symbol].iloc[:n]

    def _bars_at(self, t: int | None) -> dict[str, dict]:
        """当前时间点在交易的标的 → bar dict（撮合只用 open/high/low/close/volume）。"""
        bars: dict[str, dict] = {}
        if t is None:
            return bars
        for s, pos in self._pos.items():
            i = pos.get(t)
            if i is None:
                continue
            row = self.data[s].iloc[i]
            bars[s] = {
                "open": row["open"], "high": row["high"], "low": row["low"],
                "close": row["close"], "volume": row["volume"],
            }
        return bars

    # ---- 主循环 ----
    def run(self, strategy) -> Broker:
        if not self.times:
            return self.broker
        self._t: int | None = None
        ctx = Context(self.broker, self.symbols,
                      history_fn=self._history,
                      bars_fn=lambda: self._bars_at(self._t),
                      now_fn=lambda: self._t)
        strategy.init(ctx)          # 全量历史，可预计算指标
        for t in self.times:
            self._t = t
            self.broker.execute_pending(self._bars_at(t), t)  # 上根信号按本 bar 开盘成交
            strategy.on_bar(ctx)                              # 本 bar 收盘信息下单
            self.broker.end_of_bar()
        self._t = None
        strategy.on_finish(ctx)
        return self.broker
