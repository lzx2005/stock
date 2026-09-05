# factors.py —— import 即注册。指标引用 backtest.indicators，条件因子用 pandas 滚动算子
import backtest.indicators as ind
from factors.registry import register_factor

@register_factor("ma", inputs=("close",), default_params={"n": 20},
                 lookback=lambda p: p["n"],
                 doc="N日简单均线。同花顺条件句：MA5>MA20、收盘价>MA20 等")
def _ma(df, n=20): return ind.ma(df["close"], n)

@register_factor("ema", inputs=("close",), default_params={"n": 12},
                 lookback=0,
                 doc="N日指数均线。同花顺：EMA5、收盘价>EMA20 等")
def _ema(df, n=12): return ind.ema(df["close"], n)

@register_factor("rsi", inputs=("close",), default_params={"n": 14},
                 lookback=lambda p: p["n"],
                 doc="RSI(Wilder)。同花顺：RSI>70、RSI<30 等超买超卖条件")
def _rsi(df, n=14): return ind.rsi(df["close"], n)

@register_factor("atr", inputs=("high", "low", "close"), default_params={"n": 14},
                 lookback=lambda p: p["n"],
                 doc="平均真实波幅。同花顺：无直接对应，用于波动过滤")
def _atr(df, n=14): return ind.atr(df, n)

@register_factor("macd_hist", inputs=("close",),
                 default_params={"fast": 12, "slow": 26, "signal": 9},
                 lookback=0,
                 doc="MACD 柱(国内惯例 2*(dif-dea))。同花顺：MACD柱>0、红柱放大")
def _macd_hist(df, fast=12, slow=26, signal=9): return ind.macd(df["close"], fast, slow, signal)[2]

@register_factor("kdj_j", inputs=("high", "low", "close"), default_params={"n": 9},
                 lookback=lambda p: p["n"],
                 doc="KDJ 的 J 值。同花顺：J>100 超买、J<0 超卖")
def _kdj_j(df, n=9): return ind.kdj(df, n)[2]

@register_factor("boll_up", inputs=("close",), default_params={"n": 20, "k": 2},
                 lookback=lambda p: p["n"],
                 doc="布林上轨。同花顺：收盘价>BOLL上轨（突破）")
def _boll_up(df, n=20, k=2): return ind.boll(df["close"], n, k)[1]

@register_factor("boll_low", inputs=("close",), default_params={"n": 20, "k": 2},
                 lookback=lambda p: p["n"],
                 doc="布林下轨。同花顺：收盘价<BOLL下轨（超跌）")
def _boll_low(df, n=20, k=2): return ind.boll(df["close"], n, k)[2]

@register_factor("vol_ratio", inputs=("volume",), default_params={"n": 5},
                 lookback=lambda p: p["n"],
                 doc="量比：当日量/近n日均量。同花顺：量比>1.5（放量）")
def _vol_ratio(df, n=5): return df["volume"] / df["volume"].rolling(n).mean()

@register_factor("mom", inputs=("close",), default_params={"n": 5},
                 lookback=lambda p: p["n"],
                 doc="N日动量/涨幅。同花顺：5日涨幅>10%")
def _mom(df, n=5): return df["close"].pct_change(n)

@register_factor("bias", inputs=("close",), default_params={"n": 20},
                 lookback=lambda p: p["n"],
                 doc="乖离率：(收盘-均线)/均线。同花顺：BIAS20 超买超卖")
def _bias(df, n=20):
    m = ind.ma(df["close"], n)
    return (df["close"] - m) / m
