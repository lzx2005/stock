"""绩效统计：权益曲线（close 重估持仓）+ 收益/回撤/夏普/胜率/盈亏比/交易明细。

纯函数，输入 broker（现金/交易记录）+ 各标的收盘序列，输出报告。
- 权益曲线：回放成交记录重建每个时间点的现金+持仓，持仓按该时间点收盘价重估
- 年化按 bar 频率（period → 每年 bar 数），无风险利率 = 0
- 胜率/盈亏比基于"买-卖"配对回合（FIFO 均价），按价差计算（不含费用）
"""

from dataclasses import dataclass, field

import pandas as pd

from backtest.broker import Trade

# 每个交易日本来 240 分钟，留部分冗余用整数
_BARS_PER_YEAR = {
    "1m": 252 * 240, "5m": 252 * 48, "15m": 252 * 16, "30m": 252 * 8,
    "60m": 252 * 4, "1d": 252, "1w": 52, "1M": 12, "1Q": 4, "1Y": 1,
}


@dataclass
class RoundTrip:
    """一笔已平仓的买卖回合（FIFO 配对，价差盈亏，不含费用）。"""
    symbol: str
    shares: int
    buy_ts: int
    buy_price: float
    sell_ts: int
    sell_price: float
    pnl: float


@dataclass
class PerformanceReport:
    initial_cash: float
    final_equity: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe: float
    trade_count: int
    win_rate: float
    profit_loss_ratio: float
    trades: list[RoundTrip] = field(default_factory=list)


def _round_trips(trades: list[Trade]) -> list[RoundTrip]:
    """按 FIFO 均价把买/卖配对成回合。"""
    lots: dict[str, list] = {}  # symbol -> [(shares, avg_price, ts)]
    trips: list[RoundTrip] = []
    for tr in sorted(trades, key=lambda t: t.ts):
        if tr.side == "buy":
            lots.setdefault(tr.symbol, []).append((tr.shares, tr.price, tr.ts))
            continue
        remaining = tr.shares
        while remaining > 0 and lots.get(tr.symbol):
            sh, px, bts = lots[tr.symbol][0]
            take = min(sh, remaining)
            trips.append(RoundTrip(tr.symbol, take, bts, px, tr.ts, tr.price,
                                   (tr.price - px) * take))
            lots[tr.symbol][0] = (sh - take, px, bts)
            if lots[tr.symbol][0][0] == 0:
                lots[tr.symbol].pop(0)
            if not lots[tr.symbol]:
                lots.pop(tr.symbol, None)
            remaining -= take
    return trips


def _closes(data: dict[str, pd.DataFrame]) -> dict[str, dict[int, float]]:
    """{symbol: {timestamp: close}} 快速查询表。"""
    out = {}
    for s, df in data.items():
        out[s] = dict(zip(df["timestamp"], df["close"]))
    return out


def equity_curve(broker, data: dict[str, pd.DataFrame],
                 period: str = "1d") -> pd.DataFrame:
    """按时间并集重建权益：现金（成交回放）+ Σ 持仓 × 收盘价。"""
    closes = _closes(data)
    times = sorted({ts for df in data.values() for ts in df["timestamp"]})
    if not times:
        return pd.DataFrame(columns=["timestamp", "equity"])

    cash = broker.initial_cash
    pos: dict[str, int] = {}
    rows: list[tuple[int, float]] = []
    trades = sorted(broker.trades, key=lambda t: t.ts)
    ti = 0
    for t in times:
        while ti < len(trades) and trades[ti].ts <= t:
            tr = trades[ti]
            if tr.side == "buy":
                cash -= tr.shares * tr.price + tr.commission
                pos[tr.symbol] = pos.get(tr.symbol, 0) + tr.shares
            else:
                cash += tr.shares * tr.price - tr.commission - tr.tax
                pos[tr.symbol] = pos.get(tr.symbol, 0) - tr.shares
                if pos[tr.symbol] == 0:
                    pos.pop(tr.symbol, None)
            ti += 1
        # 持仓按当前时间点收盘价重估（无该时间点数据则跳过该标的）
        value = cash + sum(sh * closes[s].get(t, 0.0) for s, sh in pos.items()
                           if s in closes)
        rows.append((t, value))
    return pd.DataFrame(rows, columns=["timestamp", "equity"])


def analyze(broker, data: dict[str, pd.DataFrame], period: str = "1d") -> PerformanceReport:
    curve = equity_curve(broker, data, period)
    initial = broker.initial_cash
    if len(curve) == 0:
        return PerformanceReport(initial, initial, 0.0, 0.0, 0.0, 0.0,
                                 0, 0.0, 0.0, [])

    equity = curve["equity"]
    final = float(equity.iloc[-1])
    total = final / initial - 1 if initial else 0.0

    # 最大回撤
    peak = equity.cummax()
    drawdown = 1.0 - equity / peak
    max_dd = float(drawdown.max()) if len(drawdown) else 0.0

    # 年化收益
    bpy = _BARS_PER_YEAR.get(period, 252)
    n = len(equity)
    annual = (1.0 + total) ** (bpy / n) - 1.0 if n > 0 else 0.0

    # 夏普（年化，rf=0）
    rets = curve["equity"].pct_change().dropna()
    if len(rets) >= 2 and rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * (bpy ** 0.5))
    else:
        sharpe = 0.0

    # 回合统计
    trips = _round_trips(broker.trades)
    wins = [t.pnl for t in trips if t.pnl > 0]
    losses = [t.pnl for t in trips if t.pnl <= 0]
    win_rate = len(wins) / len(trips) if trips else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    if avg_loss > 0:
        pl_ratio = avg_win / avg_loss if wins else 0.0
    else:
        pl_ratio = 0.0 if not wins else float("inf")

    return PerformanceReport(initial, final, total, annual, max_dd, sharpe,
                             len(trips), win_rate, pl_ratio, trips)
