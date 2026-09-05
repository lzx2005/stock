"""策略版本对比：纯函数（无 I/O，单测友好）。

职责：
- 可比性检查：只有回测设置（symbols/period/adjust/区间/initial_cash/成本模型）
  全等时，指标差异才有意义；策略 params 不同不阻断可比（那正是被测对象）。
- 指标差值 + 方向判定 + 结论判定（progress / regress / mixed）。
- 组装 comparison.json（vs v1 + vs 上一版）。
"""

import math

# 主对比元组：判断"有没有进度"用这 4 项；其余为次要信号。
PRIMARY = ["total_return", "excess_return", "max_drawdown", "sharpe"]
SECONDARY = ["win_rate", "profit_loss_ratio", "trade_count", "final_equity"]
ALL_METRICS = PRIMARY + SECONDARY

# 指标方向：True=升为好，False=降为好，None=无方向
DIRECTIONS = {
    "total_return": True,
    "excess_return": True,
    "max_drawdown": False,
    "sharpe": True,
    "win_rate": True,
    "profit_loss_ratio": True,
    "trade_count": None,
    "final_equity": True,
}

_VERDICT_LABEL = {"progress": "进步", "regress": "退步", "mixed": "部分改善"}


def _flatten(version: dict) -> dict:
    """把 version.json 的 results 拍平为指标字典（metrics + 派生 excess_return）。"""
    results = version.get("results") or {}
    m = dict(results.get("metrics") or {})
    if results.get("excess_return") is not None:
        m["excess_return"] = results["excess_return"]
    return m


def _num(x):
    """返回可参与比较的 float；None/字符串等返回 None；inf 保留为 ±inf。"""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return None


def comparable(new_version: dict, old_version: dict) -> tuple[bool, str]:
    """回测设置全等才可比。返回 (是否可比, 不可比原因 note)。"""
    nb = new_version.get("backtest") or {}
    ob = old_version.get("backtest") or {}
    if not nb or not ob:
        return False, "缺 backtest 决定参数"
    diffs = []
    if sorted(nb.get("symbols") or []) != sorted(ob.get("symbols") or []):
        diffs.append("标的")
    if nb.get("period") != ob.get("period"):
        diffs.append("周期")
    if nb.get("adjust") != ob.get("adjust"):
        diffs.append("复权口径")
    if nb.get("initial_cash") != ob.get("initial_cash"):
        diffs.append("初始资金")
    if nb.get("start_ms") != ob.get("start_ms") or nb.get("end_ms") != ob.get("end_ms"):
        diffs.append("回测区间")
    if nb.get("broker") != ob.get("broker"):
        diffs.append("成本模型")
    if diffs:
        return False, "回测设置不一致：" + "、".join(diffs)
    return True, ""


def metric_delta(metric: str, old_metrics: dict, new_metrics: dict) -> dict:
    """单个指标的新旧差值。返回 {old, new, delta, better}。

    better 语义：升为好方向且 delta>0 → True；降为好方向且 delta<0 → True；
    delta==0 / trade_count → None（无方向/无变化）；含 inf 时 delta=None
    （避免 JSON 序列化失败），方向照判（如全赢 inf 被打破 → better=False）。
    """
    o, n = _num(old_metrics.get(metric)), _num(new_metrics.get(metric))
    if o is None or n is None:
        return {"old": old_metrics.get(metric), "new": new_metrics.get(metric),
                "delta": None, "better": None}
    delta = n - o
    if metric == "trade_count":
        better = None
    elif delta == 0:
        better = None
    else:
        better = (delta > 0) if DIRECTIONS.get(metric, True) else (delta < 0)
    if math.isinf(o) or math.isinf(n):
        delta = None
    return {"old": old_metrics.get(metric), "new": new_metrics.get(metric),
            "delta": delta, "better": better}


def excess_return(version: dict) -> float | None:
    """策略总收益 - 基准总收益（从 version.json 直接读，不自算）。"""
    results = version.get("results") or {}
    tr = (results.get("metrics") or {}).get("total_return")
    br = (results.get("benchmark") or {}).get("total_return")
    if tr is None or br is None:
        return None
    return float(tr) - float(br)


def judge_verdict(primary_deltas: dict) -> str:
    """主指标 4 项判定结论（total_return/excess_return/max_drawdown/sharpe）：
    - 无一项变差 且 (≥2 项变好 或 总收益变好) → "progress"
      —— 头部指标（总收益/超额）向上、其余不恶化即算进步，避免"没全动就只报 mixed"
    - total_return 变差 或 变差项 ≥2 → "regress"
    - 否则 "mixed"
    """
    deltas = [d for name, d in primary_deltas.items() if name in PRIMARY and d]
    better = sum(1 for d in deltas if d.get("better") is True)
    worse = sum(1 for d in deltas if d.get("better") is False)
    tr = primary_deltas.get("total_return") or {}
    tr_better = tr.get("better") is True
    tr_worse = tr.get("better") is False
    if worse == 0 and (better >= 2 or tr_better):
        return "progress"
    if tr_worse or worse >= 2:
        return "regress"
    return "mixed"


def compare_versions(new_version: dict, old_version: dict) -> dict:
    """新版本 vs 单个旧版本。不可比 → {version, comparable: False, note}；
    可比 → {version, comparable, verdict, metrics_delta{8}}。"""
    ok, note = comparable(new_version, old_version)
    if not ok:
        return {"version": old_version.get("version"), "comparable": False, "note": note}
    new_m, old_m = _flatten(new_version), _flatten(old_version)
    deltas = {m: metric_delta(m, old_m, new_m) for m in ALL_METRICS}
    return {
        "version": old_version.get("version"),
        "comparable": True,
        "verdict": judge_verdict({k: deltas[k] for k in PRIMARY}),
        "metrics_delta": deltas,
    }


def build_comparison(new_version: dict, v1: dict | None, prev: dict | None) -> dict:
    """组装完整 comparison.json：vs v1 + vs 上一版。基线缺失则对应键为 None。"""
    vs_v1 = compare_versions(new_version, v1) if v1 else None
    vs_prev = compare_versions(new_version, prev) if prev else None
    ok_v1 = bool(vs_v1 and vs_v1.get("comparable"))
    ok_prev = bool(vs_prev and vs_prev.get("comparable"))
    note = ""
    if not (ok_v1 or ok_prev):
        notes = [c.get("note", "") for c in (vs_v1, vs_prev)
                 if c and not c.get("comparable") and c.get("note")]
        note = "；".join(notes) or "无可比基线"
    return {
        "strategy_id": new_version.get("strategy_id"),
        "version": new_version.get("version"),
        "created_at_ms": new_version.get("created_at_ms"),
        "comparable": ok_v1 or ok_prev,
        "note": note,
        "primary": list(PRIMARY),
        "vs_v1": vs_v1,
        "vs_prev": vs_prev,
    }


def verdict_label(verdict: str) -> str:
    return _VERDICT_LABEL.get(verdict, verdict or "—")
