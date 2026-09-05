"""真实数据回测示例：单标的 + 多标的双均线，打印绩效 + 权益曲线。

因子值从 FactorStore 取数：首次运行计算并落盘 data/factors/，再次运行命中缓存。
运行：`source ~/.zshrc && .venv/bin/python -m examples.run_backtest`
"""

import time

import factors.factors  # noqa: F401  —— import 即注册内置因子
from datacenter import DataCenter
from backtest.engine import BacktestEngine
from backtest.performance import analyze
from examples.strategies.ma_cross import MaCross
from factors import FactorStore

YEARS = 5 * 365 * 86_400_000


def _window():
    end = int(time.time() * 1000)
    return end - YEARS, end


def _print_report(title, broker, data):
    rep = analyze(broker, data, period="1d")
    print(f"\n===== {title} =====")
    print(f"初始资金: {rep.initial_cash:,.0f}")
    print(f"期末权益: {rep.final_equity:,.2f}   总收益: {rep.total_return:+.2%}   年化: {rep.annual_return:+.2%}")
    print(f"最大回撤: {rep.max_drawdown:.2%}   夏普: {rep.sharpe:.2f}")
    print(f"交易次数: {rep.trade_count}   胜率: {rep.win_rate:.1%}   盈亏比: {rep.profit_loss_ratio:.2f}")
    if rep.trades:
        print("交易明细（最近 5 笔）:")
        for t in rep.trades[-5:]:
            print(f"  {t.symbol} {t.buy_ts} 买@{t.buy_price:.2f} -> {t.sell_ts} 卖@{t.sell_price:.2f} "
                  f"x{t.shares}  盈亏 {t.pnl:+.0f}")
    curve = _equity_curve(broker, data)
    print(f"权益曲线（首/尾/抽样）: {[round(v, 0) for v in curve['equity'].iloc[[0, -1]].tolist()]} ...")
    return rep


def _equity_curve(broker, data):
    from backtest.performance import equity_curve
    return equity_curve(broker, data, period="1d")


def run_single():
    start, end = _window()
    dc = DataCenter()
    eng = BacktestEngine(dc, ["600000.SH"], period="1d", start_ms=start, end_ms=end,
                         initial_cash=1_000_000)
    eng.run(MaCross(5, 20, fs=FactorStore(dc)))
    _print_report("600000.SH 双均线(5/20) 日线 5 年", eng.broker, eng.data)


def run_multi():
    start, end = _window()
    dc = DataCenter()
    symbols = ["600000.SH", "000001.SZ", "600519.SH"]
    eng = BacktestEngine(dc, symbols, period="1d", start_ms=start, end_ms=end,
                         initial_cash=1_000_000)
    eng.run(MaCross(5, 20, fs=FactorStore(dc)))
    _print_report("多标的共享资金池 双均线(5/20) 日线 5 年", eng.broker, eng.data)


if __name__ == "__main__":
    run_single()
    run_multi()
