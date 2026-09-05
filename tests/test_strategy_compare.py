"""策略版本对比纯函数测试（无 I/O）。"""

from strategy import compare as C

BASE_BROKER = {"commission": 0.0003, "min_commission": 5.0, "stamp_tax": 0.0005,
               "slippage": 0.0, "lot_size": 100, "t_plus_1": True}


def mk_version(version=1, *, total_return=0.05, excess=0.10, max_drawdown=0.2,
               sharpe=0.5, win_rate=0.6, pl_ratio=0.8, trade_count=20,
               final_equity=1050000, adjust="forward", period="1d",
               symbols=None, initial_cash=1000000, start_ms=1000, end_ms=2000,
               broker=None):
    symbols = symbols or ["600519.SH"]
    broker = broker or BASE_BROKER
    return {
        "version": version,
        "strategy_id": 1,
        "results": {
            "metrics": {
                "total_return": total_return,
                "annual_return": total_return,
                "max_drawdown": max_drawdown,
                "sharpe": sharpe,
                "win_rate": win_rate,
                "profit_loss_ratio": pl_ratio,
                "trade_count": trade_count,
                "final_equity": final_equity,
            },
            "benchmark": {"name": "买入持有", "total_return": total_return - excess},
            "excess_return": excess,
        },
        "backtest": {
            "symbols": symbols, "period": period, "adjust": adjust,
            "start_ms": start_ms, "end_ms": end_ms,
            "initial_cash": initial_cash, "broker": broker,
        },
    }


def test_comparable_true_when_settings_equal():
    ok, note = C.comparable(mk_version(2), mk_version(1))
    assert ok is True and note == ""


def test_comparable_false_dimensions():
    v1 = mk_version(1)
    cases = {
        "symbols": mk_version(2, symbols=["000001.SZ"]),
        "period": mk_version(2, period="1w"),
        "adjust": mk_version(2, adjust="backward"),
        "initial_cash": mk_version(2, initial_cash=2_000_000),
        "区间(start_ms)": mk_version(2, start_ms=0),
        "成本模型(commission)": mk_version(2, broker={**BASE_BROKER, "commission": 0.001}),
    }
    for name, v2 in cases.items():
        ok, note = C.comparable(v2, v1)
        assert ok is False, name
        assert note, name


def test_comparable_missing_backtest():
    v2 = mk_version(2)
    v2["backtest"] = {}
    ok, note = C.comparable(v2, mk_version(1))
    assert ok is False and note


def test_metric_delta_direction():
    old = {"total_return": 0.05, "max_drawdown": 0.3, "trade_count": 20,
           "excess_return": 0.02}
    new = {"total_return": 0.10, "max_drawdown": 0.15, "trade_count": 25,
           "excess_return": 0.07}
    assert C.metric_delta("total_return", old, new)["better"] is True
    assert C.metric_delta("max_drawdown", old, new)["better"] is True   # 降为好
    assert C.metric_delta("total_return", old, new)["delta"] == 0.05
    assert C.metric_delta("trade_count", old, new)["better"] is None    # 无方向
    # 无变化 → better None
    assert C.metric_delta("total_return", old, {"total_return": 0.05})["better"] is None


def test_metric_delta_pl_ratio_inf():
    old = {"profit_loss_ratio": float("inf")}     # 全赢基线
    new = {"profit_loss_ratio": 1.5}              # 出现亏损
    d = C.metric_delta("profit_loss_ratio", old, new)
    assert d["delta"] is None                     # inf 差值不可序列化
    assert d["better"] is False                   # 全赢被打破 = 退步
    # 反向：基线有限 → 新版全赢 inf
    d2 = C.metric_delta("profit_loss_ratio", {"profit_loss_ratio": 1.5},
                        {"profit_loss_ratio": float("inf")})
    assert d2["better"] is True and d2["delta"] is None


def test_metric_delta_missing_metric():
    d = C.metric_delta("sharpe", {}, {"sharpe": 0.5})
    assert d["better"] is None and d["delta"] is None


def test_excess_return():
    v = mk_version(1, total_return=0.05, excess=0.10)
    assert C.excess_return(v) == 0.10
    v["results"]["benchmark"] = {}
    assert C.excess_return(v) is None


def test_judge_verdict_states():
    mk = lambda tr, ex, dd, sh: {"total_return": {"better": tr},
                                 "excess_return": {"better": ex},
                                 "max_drawdown": {"better": dd},
                                 "sharpe": {"better": sh}}
    assert C.judge_verdict(mk(True, True, True, True)) == "progress"
    assert C.judge_verdict(mk(True, True, True, None)) == "progress"    # 3 better 0 worse
    assert C.judge_verdict(mk(False, True, True, True)) == "regress"    # total_return 变差
    assert C.judge_verdict(mk(True, True, False, False)) == "regress"   # worse>=2
    assert C.judge_verdict(mk(True, True, None, None)) == "progress"   # 头指标向好、无变差
    assert C.judge_verdict(mk(True, None, None, None)) == "progress"   # 总收益变好、无变差即进步
    assert C.judge_verdict(mk(None, True, None, None)) == "mixed"      # 仅超额变好、总收益持平
    assert C.judge_verdict(mk(None, None, None, None)) == "mixed"


def test_compare_versions_comparable():
    v2 = mk_version(2, total_return=0.10, excess=0.12)
    v1 = mk_version(1, total_return=0.05, excess=0.08)
    out = C.compare_versions(v2, v1)
    assert out["comparable"] is True and out["version"] == 1
    assert out["verdict"] in ("progress", "regress", "mixed")
    assert set(out["metrics_delta"]) == set(C.ALL_METRICS)
    assert out["metrics_delta"]["total_return"]["delta"] == 0.05


def test_compare_versions_not_comparable():
    v2 = mk_version(2, period="1w")
    out = C.compare_versions(v2, mk_version(1))
    assert out["comparable"] is False and "周期" in out["note"]
    assert "verdict" not in out


def test_build_comparison_assembles_vs_v1_and_prev():
    v1 = mk_version(1, total_return=0.05)
    v2 = mk_version(2, total_return=0.10)
    v3 = mk_version(3, total_return=0.12)
    out = C.build_comparison(v3, v1, v2)
    assert out["version"] == 3 and out["comparable"] is True
    assert out["vs_v1"]["version"] == 1 and out["vs_prev"]["version"] == 2
    assert out["vs_v1"]["verdict"] and out["vs_prev"]["verdict"]


def test_build_comparison_no_v1():
    v2 = mk_version(2)
    out = C.build_comparison(v2, None, mk_version(1))
    assert out["vs_v1"] is None and out["vs_prev"] is not None


def test_build_comparison_all_not_comparable():
    v2 = mk_version(2, adjust="backward")
    out = C.build_comparison(v2, mk_version(1), mk_version(1))
    assert out["comparable"] is False and out["note"]


def test_verdict_label():
    assert C.verdict_label("progress") == "进步"
    assert C.verdict_label("regress") == "退步"
    assert C.verdict_label("mixed") == "部分改善"
    assert C.verdict_label("") == "—"
