#!/usr/bin/env python3
"""交割单复盘分析：结构化 trades JSON → 客观分析 JSON。

用法（在项目根目录运行）:
    source ~/.zshrc   # 载入 TICKFLOW_API_KEY；数据缺时回源补数据需要
    .venv/bin/python .claude/skills/trade-review/scripts/analyze_trades.py \
        --trades trades.json [--out analysis.json] [--lookback 400]

输入 trades.json：交易所 JSON 数组，每条：
    {"date": "2026-08-05",            # 交易日（或 "2026-08-05 10:32"）
     "symbol": "600000.SH",           # 代码，六位纯数字会自动补 .SH/.SZ/.BJ
     "name": "浦发银行",              # 可选，仅用于报告显示
     "side": "buy" | "sell",
     "shares": 1000, "price": 8.35}

输出：分析 JSON（打印到 stdout，也可 --out 写文件）。要点：
- 每个成交单的时机特征：当日价格位置 pos_in_range、动量、趋势、RSI/MACD、
  量比、距 20 日高点距离等——全部只用"当日及之前"的数据（指标因果、无前视）
- 卖出单的 forward 收益（卖出后 1/5/10 日涨跌）→ 识别"卖飞"
- FIFO 买卖回合（复用 backtest.performance._round_trips）：持仓天数 + 价差盈亏
- 行为画像 + 亏损归因（追高/逆势/扛单/频繁交易，按金额汇总）
- 数据缺口清单（交易无行情覆盖）

关键约定：全部用 adjust="none" 原始价日线。交割单成交价是历史实际价，
原始价可与之直接比较；复权价会改写历史价格，反而对不上。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 定位项目根目录（含 src/backtest），以便 import 项目内模块
_ROOT = Path(__file__).resolve()
for _ in range(6):
    if (_ROOT / "src" / "backtest").is_dir():
        break
    _ROOT = _ROOT.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from backtest.broker import Trade
from backtest.indicators import ma, macd, rsi
from backtest.performance import _round_trips

DATA_DIR = _ROOT / "data"
DAY_MS = 86_400_000

# 亏损归因优先级：追高 > 逆势 > 扛单 > 频繁交易 > 其他
CATEGORIES = ["追高买入", "逆势买入", "止损过晚/扛单", "频繁交易磨损", "其他"]

_ks = None  # 无 API Key 时的只读 fallback


def parse_date(s: str) -> pd.Timestamp:
    """'2026-08-05' / '20260805' / '2026-08-05 10:32' → 北京时区当日零点。"""
    return pd.Timestamp(s.strip()[:10], tz="Asia/Shanghai")


def day_ms(ts: pd.Timestamp) -> int:
    return int(ts.value // 10**6)


def ts_to_date(ms: int) -> str:
    return pd.Timestamp(ms, unit="ms", tz="Asia/Shanghai").strftime("%Y-%m-%d")


def normalize_symbol(s: str) -> str:
    s = s.strip().upper().replace(" ", "")
    if "." in s:
        return s
    if len(s) != 6 or not s.isdigit():
        return s
    if s.startswith(("600", "601", "603", "605", "688", "689", "900", "999")):
        return s + ".SH"
    if s.startswith(("000", "001", "002", "003", "300", "301", "200", "399")):
        return s + ".SZ"
    if s.startswith(("920", "8", "4")):
        return s + ".BJ"
    return s


def load_trades(path: str) -> list[dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("trades", raw)
    trades = []
    for r in raw:
        side = str(r["side"]).strip().lower()
        side = {"b": "buy", "buy": "buy", "买": "buy", "买入": "buy",
                "s": "sell", "sell": "sell", "卖": "sell", "卖出": "sell"}.get(side)
        if side is None:
            raise ValueError(f"未知 side: {r['side']}")
        trades.append({
            "date": parse_date(r["date"]),
            "symbol": normalize_symbol(r["symbol"]),
            "name": r.get("name", ""),
            "side": side,
            "shares": int(r["shares"]),
            "price": float(r["price"]),
        })
    trades.sort(key=lambda t: (t["date"], t["symbol"]))
    return trades


def try_datacenter():
    """优先完整 DataCenter（可回源补缺口）；无 API Key 则退回只读 KlineStore。"""
    global _ks
    try:
        from datacenter import DataCenter
        return DataCenter(data_dir=str(DATA_DIR)), True
    except Exception:
        from datacenter.store.klines import KlineStore
        _ks = KlineStore(DATA_DIR / "klines")
        return None, False


def fetch_daily(dc, sym: str, start_ms: int, end_ms: int) -> pd.DataFrame | None:
    try:
        if dc is not None:
            df = dc.get_klines(sym, "1d", start_ms, end_ms, adjust="none")
        else:
            df = _ks.read([sym], "1d", start_ms, end_ms)
        return normalize_df(df, sym)
    except Exception:
        return None


def normalize_df(df: pd.DataFrame, sym: str) -> pd.DataFrame | None:
    """K线 df → 以北京当日 0 点为索引、按日期升序的日线表。"""
    if df is None or df.empty:
        return None
    df = df.copy()
    if "symbol" in df.columns:
        df = df[df["symbol"] == sym]
    if df.empty:
        return None
    df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    idx = pd.to_datetime(df["timestamp"], unit="ms", utc=True) \
        .dt.tz_convert("Asia/Shanghai").dt.normalize()
    df.index = idx
    df.index.name = "date"
    return df


def enrich(df: pd.DataFrame) -> None:
    """加指标列（rolling/ewm 均因果，索引当日即"截至当日"的值）。"""
    c = df["close"]
    df["ma5"] = ma(c, 5)
    df["ma10"] = ma(c, 10)
    df["ma20"] = ma(c, 20)
    df["ma60"] = ma(c, 60)
    df["rsi14"] = rsi(c, 14)
    dif, dea, hist = macd(c)
    df["macd_dif"], df["macd_dea"], df["macd_hist"] = dif, dea, hist
    df["hhv20"] = c.rolling(20).max()


def _fnum(v):
    return None if v is None or pd.isna(v) else round(float(v), 4)


def compute_features(df: pd.DataFrame, i: int, price: float) -> dict:
    """bar i 处、以 price 成交的时机特征。只用 ≤ i 的数据，无前视。"""
    c = df["close"]
    bar = df.iloc[i]
    f: dict = {}
    rng = bar["high"] - bar["low"]
    f["pos_in_range"] = _fnum((price - bar["low"]) / rng) if rng > 0 else 0.5
    prev = c.iloc[i - 1] if i >= 1 else bar["open"]
    f["open_gap_pct"] = _fnum(bar["open"] / prev - 1)
    f["day_change_pct"] = _fnum(bar["close"] / prev - 1)
    f["close_vs_fill_pct"] = _fnum(bar["close"] / price - 1)  # >0 收盘高于成交价
    for n in (5, 10, 20, 60):
        mv = df[f"ma{n}"].iloc[i]
        f[f"price_vs_ma{n}_pct"] = _fnum(price / mv - 1) if mv and mv == mv else None
    m5, m20 = df["ma5"].iloc[i], df["ma20"].iloc[i]
    f["ma5_vs_ma20_pct"] = _fnum(m5 / m20 - 1) if m5 and m20 and m20 == m20 else None
    f["rsi14"] = _fnum(df["rsi14"].iloc[i])
    f["macd_hist"] = _fnum(df["macd_hist"].iloc[i])
    f["mom_5d_pct"] = _fnum(c.iloc[i] / c.iloc[max(0, i - 5)] - 1) if i >= 5 else None
    f["mom_20d_pct"] = _fnum(c.iloc[i] / c.iloc[max(0, i - 20)] - 1) if i >= 20 else None
    if i >= 20:
        avg_vol = df["volume"].iloc[i - 20:i].mean()
        f["vol_ratio"] = _fnum(bar["volume"] / avg_vol) if avg_vol and avg_vol > 0 else None
    else:
        f["vol_ratio"] = None
    hh = df["hhv20"].iloc[i]
    f["dist_20d_high_pct"] = _fnum(price / hh - 1) if hh and hh == hh else None
    if m5 and m20 and m5 == m5 and m20 == m20:
        f["trend"] = ("up" if (m5 > m20 and price > m20) else
                      "down" if (m5 < m20 and price < m20) else "sideways")
    else:
        f["trend"] = "unknown"
    return f


def _chase(f: dict) -> bool:
    """追高风险判定：当日高位 / 5日急涨 / 月内大涨 / 远超 MA20 / RSI 过热。"""
    mom5 = f.get("mom_5d_pct") or 0
    mom20 = f.get("mom_20d_pct") or 0
    p20 = f.get("price_vs_ma20_pct") or 0
    return (f["pos_in_range"] >= 0.7 or mom5 >= 0.08 or (f["rsi14"] or 0) >= 70
            or mom20 >= 0.25 or p20 >= 0.15)


def buy_flags(f: dict) -> list[str]:
    flags = []
    if _chase(f):
        flags.append("追高")
    if f["trend"] == "down":
        flags.append("逆势")
    if f["trend"] == "up" and f["pos_in_range"] <= 0.35:
        flags.append("低位")
    p20 = f["price_vs_ma20_pct"]
    if p20 is not None and -0.03 <= p20 <= 0.01:
        flags.append("均线附近")
    return flags


def sell_flags(f: dict) -> list[str]:
    flags = []
    if f["pos_in_range"] >= 0.65:
        flags.append("高位卖出")
    if f["pos_in_range"] <= 0.3:
        flags.append("低位卖出")
    if (f["day_change_pct"] or 0) <= -0.03:
        flags.append("下跌日卖出")
    return flags


def forward_returns(df: pd.DataFrame, i: int) -> dict:
    """卖出后 1/5/10 日收益（可能为 None = 数据不足）。"""
    c = df["close"]
    out = {}
    for k in (1, 5, 10):
        j = i + k
        out[f"fwd_{k}d_pct"] = _fnum(c.iloc[j] / c.iloc[i] - 1) if j < len(c) else None
    return out


def attribute_loss(rt: dict) -> str:
    e = rt["entry"]
    if _chase(e):
        return "追高买入"
    if e["trend"] == "down":
        return "逆势买入"
    if rt["holding_days"] >= 15 and rt["return_pct"] <= -0.12:
        return "止损过晚/扛单"
    if rt["holding_days"] <= 3:
        return "频繁交易磨损"
    return "其他"


def open_positions(trades: list[dict], by_symbol: dict[str, pd.DataFrame]) -> list[dict]:
    """FIFO 消耗后的剩余持仓（未平仓部分），用最新收盘估算浮盈。"""
    lots: dict[str, list[tuple[int, float]]] = {}
    for t in trades:
        sym = t["symbol"]
        if t["side"] == "buy":
            lots.setdefault(sym, []).append((t["shares"], t["price"]))
        else:
            rem = t["shares"]
            while rem > 0 and lots.get(sym):
                sh, px = lots[sym][0]
                take = min(sh, rem)
                lots[sym][0] = (sh - take, px)
                if lots[sym][0][0] == 0:
                    lots[sym].pop(0)
                rem -= take
    out = []
    for sym, lotlist in lots.items():
        if not lotlist:
            continue
        sh = sum(l[0] for l in lotlist)
        avg = sum(l[0] * l[1] for l in lotlist) / sh
        last = by_symbol[sym]["close"].iloc[-1] if sym in by_symbol else None
        out.append({
            "symbol": sym,
            "shares": sh,
            "avg_cost": round(avg, 3),
            "last_close": round(float(last), 3) if last is not None and last == last else None,
            "unrealized_pnl": round(float((last - avg) * sh), 2) if last is not None and last == last else None,
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True, help="结构化成交单 JSON")
    ap.add_argument("--out", default=None, help="分析 JSON 写出路径（默认只打印）")
    ap.add_argument("--lookback", type=int, default=400, help="首笔交易前预取多少天（指标预热）")
    args = ap.parse_args()

    trades = load_trades(args.trades)
    if not trades:
        sys.exit("错误：无成交记录")

    min_day = min(t["date"] for t in trades)
    max_day = max(t["date"] for t in trades)
    start_ms = day_ms(min_day) - args.lookback * DAY_MS
    end_ms = day_ms(max_day) + 15 * DAY_MS

    dc, fetchable = try_datacenter()

    by_symbol: dict[str, pd.DataFrame] = {}
    gaps: list[dict] = []
    for sym in sorted({t["symbol"] for t in trades}):
        df = fetch_daily(dc, sym, start_ms, end_ms)
        if df is None:
            for t in trades:
                if t["symbol"] == sym:
                    gaps.append({"date": ts_to_date(day_ms(t["date"])), "symbol": sym,
                                 "name": t["name"], "side": t["side"],
                                 "shares": t["shares"], "price": t["price"],
                                 "reason": "无该标的行情数据"})
            continue
        enrich(df)
        by_symbol[sym] = df

    # ---- 逐笔特征 ----
    per_trade: list[dict] = []
    loc: dict[tuple[str, str], tuple[pd.DataFrame, int]] = {}  # (symbol, date) -> (df, idx)
    for t in trades:
        date_str = ts_to_date(day_ms(t["date"]))
        base = {"date": date_str, "symbol": t["symbol"], "name": t["name"],
                "side": t["side"], "shares": t["shares"], "price": t["price"]}
        df = by_symbol.get(t["symbol"])
        if df is None:
            per_trade.append({**base, "missing": True, "reason": "无行情"})
            continue
        idx = df.index.get_indexer([t["date"]], method="pad")[0]
        if idx < 0:
            per_trade.append({**base, "missing": True, "reason": "交易早于数据起点"})
            continue
        bar_date = df.index[idx]
        if t["date"] > bar_date and (t["date"] - bar_date) > pd.Timedelta(days=5):
            per_trade.append({**base, "missing": True, "reason": "交易日晚于数据末端"})
            continue
        feats = compute_features(df, idx, t["price"])
        rec = {**base, "missing": False,
               "bar_date": bar_date.strftime("%Y-%m-%d"),
               "aligned": bar_date != t["date"],
               "features": feats,
               "flags": buy_flags(feats) if t["side"] == "buy" else sell_flags(feats)}
        if t["side"] == "sell":
            rec["forward"] = forward_returns(df, idx)
        per_trade.append(rec)
        loc[(t["symbol"], date_str)] = (df, idx)

    # ---- 回合配对 ----
    objs = [Trade(t["symbol"], t["side"], t["shares"], t["price"], 0.0, 0.0, day_ms(t["date"]))
            for t in trades]
    names = {}
    for t in trades:
        if t["name"]:
            names.setdefault(t["symbol"], t["name"])

    round_trips: list[dict] = []
    for rt in _round_trips(objs):
        buy_d, sell_d = ts_to_date(rt.buy_ts), ts_to_date(rt.sell_ts)
        entry = exit_ = None
        edf, eidx = loc.get((rt.symbol, buy_d), (None, None))
        sdf, sidx = loc.get((rt.symbol, sell_d), (None, None))
        if edf is not None and eidx is not None:
            entry = compute_features(edf, eidx, rt.buy_price)
        if sdf is not None and sidx is not None:
            exit_ = {**compute_features(sdf, sidx, rt.sell_price),
                     **forward_returns(sdf, sidx)}
        holding = round((rt.sell_ts - rt.buy_ts) / DAY_MS, 1)
        ret = rt.sell_price / rt.buy_price - 1 if rt.buy_price else 0.0
        trip = {"symbol": rt.symbol, "name": names.get(rt.symbol, ""),
                "shares": rt.shares,
                "buy_date": buy_d, "buy_price": round(rt.buy_price, 3),
                "sell_date": sell_d, "sell_price": round(rt.sell_price, 3),
                "holding_days": holding, "pnl": round(rt.pnl, 2),
                "return_pct": round(ret, 4),
                "entry": entry or {}, "exit": exit_ or {},
                "entry_flags": buy_flags(entry) if entry else [],
                "exit_flags": sell_flags(exit_) if exit_ else []}
        if rt.pnl < 0:
            trip["attribution"] = attribute_loss(trip)
        round_trips.append(trip)

    # ---- 行为画像 ----
    wins = [r for r in round_trips if r["pnl"] > 0]
    losses = [r for r in round_trips if r["pnl"] <= 0]
    total_pnl = sum(r["pnl"] for r in round_trips)
    avg_win = sum(r["pnl"] for r in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(r["pnl"] for r in losses) / len(losses)) if losses else 0.0

    buys = [p for p in per_trade if not p["missing"] and p["side"] == "buy"]
    sells = [p for p in per_trade if not p["missing"] and p["side"] == "sell"]

    def mean(key, recs, src="features"):
        vals = [r[src][key] for r in recs if r[src].get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    behavior = {
        "realized_pnl": round(total_pnl, 2),
        "win_rate": round(len(wins) / len(round_trips), 3) if round_trips else None,
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
        "profit_factor": round(sum(r["pnl"] for r in wins) / abs(sum(r["pnl"] for r in losses)), 2)
                          if losses and sum(r["pnl"] for r in losses) else None,
        "num_round_trips": len(round_trips),
        "avg_holding_days": round(sum(r["holding_days"] for r in round_trips) / len(round_trips), 1)
                            if round_trips else None,
        "avg_buy_pos_in_range": mean("pos_in_range", buys),
        "avg_buy_mom_5d_pct": mean("mom_5d_pct", buys),
        "avg_buy_rsi": mean("rsi14", buys),
        "pct_buys_near_20d_high": None if not buys else round(
            sum(1 for r in buys if (r["features"].get("dist_20d_high_pct") or -9) > -0.02) / len(buys), 3),
        "pct_buys_against_downtrend": None if not buys else round(
            sum(1 for r in buys if r["features"].get("trend") == "down") / len(buys), 3),
        "avg_sell_fwd_5d_pct": mean("fwd_5d_pct", sells, src="forward"),
        "avg_sell_fwd_10d_pct": mean("fwd_10d_pct", sells, src="forward"),
        "pct_sells_fwd10_up": None if not sells else round(
            sum(1 for r in sells if (r["forward"].get("fwd_10d_pct") or 0) > 0) / len(sells), 3),
    }

    # 亏损归因（按类别汇总金额）
    attr: dict[str, dict] = {c: {"count": 0, "amount": 0.0} for c in CATEGORIES}
    for r in round_trips:
        if r["pnl"] < 0:
            c = r.get("attribution", "其他")
            attr[c]["count"] += 1
            attr[c]["amount"] += r["pnl"]
    loss_attribution = [{"category": c, "count": d["count"], "amount": round(d["amount"], 2)}
                        for c, d in attr.items() if d["count"]]

    # 止盈过早：赢单但卖出后继续大涨
    early_exit = [{"symbol": r["symbol"], "sell_date": r["sell_date"], "pnl": r["pnl"],
                   "fwd_5d_pct": r["exit"].get("fwd_5d_pct")}
                  for r in wins if (r["exit"].get("fwd_5d_pct") or 0) >= 0.03]

    # 分标的
    by_sym: dict[str, dict] = {}
    for r in round_trips:
        s = by_sym.setdefault(r["symbol"], {"pnl": 0.0, "num_trips": 0, "wins": 0})
        s["pnl"] += r["pnl"]
        s["num_trips"] += 1
        s["wins"] += 1 if r["pnl"] > 0 else 0
    for s in by_sym.values():
        s["pnl"] = round(s["pnl"], 2)
        s["win_rate"] = round(s["wins"] / s["num_trips"], 3)

    result = {
        "meta": {"script": "analyze_trades.py", "version": "1.0",
                 "period": "1d", "adjust": "none", "data_dir": str(DATA_DIR),
                 "fetchable": fetchable,
                 "note": "价差口径：回合盈亏不含佣金/印花税（交割单里另有费用行）"},
        "data_quality": {
            "total_trades": len(trades),
            "with_data": sum(1 for p in per_trade if not p["missing"]),
            "gaps": [g for g in gaps] + [p for p in per_trade if p["missing"]],
        },
        "summary": {
            "date_range": [ts_to_date(day_ms(min_day)), ts_to_date(day_ms(max_day))],
            "num_symbols": len(by_symbol),
            "buys": len(buys), "sells": len(sells),
        },
        "behavior": behavior,
        "loss_attribution": loss_attribution,
        "early_exit_winners": early_exit,
        "by_symbol": by_sym,
        "open_positions": open_positions(trades, by_symbol),
        "round_trips": round_trips,
        "per_trade": per_trade,
    }

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
