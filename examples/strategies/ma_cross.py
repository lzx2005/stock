"""示例策略：双均线金叉/死叉。因子值从 FactorStore 惰性取数（算一次存库，回测复用）。

- 快线（默认 5 日）上穿慢线（默认 20 日）-> 全仓买入；下穿 -> 清仓
- 滚动指标因果、无前视：init 一次性取整段因子序列，on_bar 按时间戳对齐
- fs 为 None 时行为不变（保持原现算路径，供测试/对比）
"""
from backtest.indicators import ma
from backtest.strategy import Strategy


class MaCross(Strategy):
    def __init__(self, short: int = 5, long: int = 20, fs=None):
        self.short = short
        self.long = long
        self.fs = fs

    def init(self, ctx) -> None:
        self.ma_s, self.ma_l = {}, {}
        if self.fs is None:
            return  # 无 fs：走 on_bar 现算路径（行为不变）
        for symbol in ctx.symbols:
            h = ctx.history(symbol)
            if h.empty:
                continue
            ts = h["timestamp"]
            self.ma_s[symbol] = self.fs.get(symbol, "ma", {"n": self.short}, "1d",
                                            int(ts.min()), int(ts.max()))
            self.ma_l[symbol] = self.fs.get(symbol, "ma", {"n": self.long}, "1d",
                                            int(ts.min()), int(ts.max()))

    def on_bar(self, ctx) -> None:
        for symbol in ctx.symbols:
            h = ctx.history(symbol)
            if len(h) < self.long + 1:
                continue  # 慢线还没满窗口，不交易
            ts = h["timestamp"]
            if self.fs is not None:
                s = self.ma_s[symbol].loc[ts.iloc[-1]]
                l = self.ma_l[symbol].loc[ts.iloc[-1]]
                s_prev = self.ma_s[symbol].loc[ts.iloc[-2]]
                l_prev = self.ma_l[symbol].loc[ts.iloc[-2]]
            else:
                s_series = ma(h["close"], self.short)
                l_series = ma(h["close"], self.long)
                s, l = s_series.iloc[-1], l_series.iloc[-1]
                s_prev, l_prev = s_series.iloc[-2], l_series.iloc[-2]
            held = symbol in ctx.positions
            if s_prev <= l_prev and s > l:      # 金叉
                ctx.buy(symbol)                  # shares=None 全仓
            elif held and s_prev >= l_prev and s < l:  # 死叉
                ctx.sell(symbol)
