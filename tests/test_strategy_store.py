"""策略库存储测试（目录式 JSON，无 DataCenter/网络依赖）。"""

import json

import pytest

from strategy import StrategyNotFoundError, StrategyStore, VersionNotFoundError

BROKER = {"commission": 0.0003, "min_commission": 5.0, "stamp_tax": 0.0005,
          "slippage": 0.0, "lot_size": 100, "t_plus_1": True}


def make_results(total_return=-0.05, benchmark=-0.22):
    return {
        "strategy_name": "测试策略",
        "requirement": "用户需求原话",
        "assumptions": ["假设"],
        "symbols": ["600519.SH"],
        "period": "1d",
        "start": "2023-08-29", "end": "2026-08-28",
        "initial_cash": 1000000,
        "strategy_logic": "5/20 金叉买，ATR 止损卖",
        "matching": "信号次日开盘撮合，T+1",
        "metrics": {
            "total_return": total_return,
            "annual_return": -0.017,
            "max_drawdown": 0.16,
            "sharpe": 0.4,
            "trade_count": 25,
            "win_rate": 0.6,
            "profit_loss_ratio": 0.6,
            "final_equity": 950000,
        },
        "benchmark": {"name": "买入持有", "total_return": benchmark},
        "trades": [{"symbol": "600519.SH", "buy_date": "2023-10-01", "buy_price": 100,
                    "sell_date": "2023-10-05", "sell_price": 105, "shares": 100, "pnl": 500}],
        "entry_exit": {"strategy": "s", "entry": "e", "exit": "x", "conditions": "c"},
    }


def make_meta(strategy_class="MaCrossAtrStop", adjust="forward", broker=None):
    return {
        "strategy_class": strategy_class,
        "params": {"fast": 5, "slow": 20, "atr_n": 14, "stop_atr_k": 2},
        "change_note": "",
        "adjust": adjust,
        "broker": broker or BROKER,
        "start_ms": 1693267200000,
        "end_ms": 1756252800000,
    }


def write_report_dir(tmp_path, *, name="reports", total_return=-0.05, benchmark=-0.22,
                     adjust="forward", broker=None, meta=True):
    """造一个 skill 产物目录（results.json + backtest_meta.json + 源码）。"""
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.json").write_text(json.dumps(make_results(total_return, benchmark),
                                               ensure_ascii=False), encoding="utf-8")
    if meta:
        (d / "backtest_meta.json").write_text(json.dumps(make_meta(adjust=adjust,
                                                                   broker=broker)),
                                              encoding="utf-8")
    (d / "equity.csv").write_text("timestamp,equity\n1,100\n2,110\n", encoding="utf-8")
    (d / "report.md").write_text("# 报告\n内容\n", encoding="utf-8")
    (d / "strategy_ma_cross_atr.py").write_text("class MaCrossAtrStop: pass\n", encoding="utf-8")
    (d / "run_backtest.py").write_text("print('run')\n", encoding="utf-8")
    (d / "__pycache__").mkdir(exist_ok=True)
    return d


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------- 策略级 ----------------

def test_create_strategy_increments_id(tmp_path):
    s = StrategyStore(root=tmp_path / "data" / "strategies")
    assert s.create_strategy("A") == 1
    assert s.create_strategy("B") == 2
    manifest = load(tmp_path / "data" / "strategies" / "manifest.json")
    assert manifest["next_id"] == 3
    info = load(tmp_path / "data" / "strategies" / "1" / "strategy.json")
    assert info["name"] == "A" and info["latest_version"] == 0


def test_create_empty_name_raises(tmp_path):
    s = StrategyStore(root=tmp_path / "strategies")
    with pytest.raises(Exception):
        s.create_strategy("   ")


def test_list_strategies_empty_and_with_data(tmp_path):
    s = StrategyStore(root=tmp_path / "strategies")
    assert s.list_strategies() == []
    s.create_strategy("A")
    s.create_strategy("B")
    rows = s.list_strategies()
    assert [r["id"] for r in rows] == [1, 2]
    assert rows[0]["name"] == "A" and rows[0]["latest_version"] == 0
    assert rows[0]["latest"] is None


def test_get_and_rename(tmp_path):
    s = StrategyStore(root=tmp_path / "strategies")
    sid = s.create_strategy("旧名", "描述")
    assert s.get_strategy(sid)["name"] == "旧名"
    s.rename_strategy(sid, "新名")
    assert s.get_strategy(sid)["name"] == "新名"
    with pytest.raises(StrategyNotFoundError):
        s.get_strategy(99)


def test_delete_strategy_and_id_not_reused(tmp_path):
    s = StrategyStore(root=tmp_path / "strategies")
    a = s.create_strategy("A")
    s.delete_strategy(a)
    with pytest.raises(StrategyNotFoundError):
        s.get_strategy(a)
    assert s.create_strategy("B") == 2          # 删除后 id 不重用
    with pytest.raises(StrategyNotFoundError):
        s.delete_strategy(99)


# ---------------- 版本级 ----------------

def test_import_version_v1_layout(tmp_path):
    s = StrategyStore(root=tmp_path / "strategies")
    sid = s.create_strategy("测试策略")
    src = write_report_dir(tmp_path)
    assert s.import_version(sid, src) == 1

    vdir = tmp_path / "strategies" / "1" / "versions" / "1"
    assert (vdir / "results.json").exists()
    assert (vdir / "equity.csv").exists()
    assert (vdir / "report.md").exists()
    assert (vdir / "strategy_v1.py").exists()           # strategy_*.py 改名复制
    assert (vdir / "run_backtest.py").exists()
    assert not (vdir / "__pycache__").exists()          # 不复制 __pycache__
    assert not (vdir / "comparison.json").exists()      # v1 无对比
    assert s.get_strategy(sid)["latest_version"] == 1

    v = load(vdir / "version.json")
    assert v["version"] == 1 and v["strategy_class"] == "MaCrossAtrStop"
    assert v["backtest"]["adjust"] == "forward"
    assert v["backtest"]["broker"] == BROKER
    assert v["backtest"]["start_ms"] == 1693267200000
    assert v["results"]["metrics"]["total_return"] == -0.05
    assert v["results"]["excess_return"] == pytest.approx(-0.05 - (-0.22))  # 0.17


def test_import_version_missing_results_raises(tmp_path):
    s = StrategyStore(root=tmp_path / "strategies")
    sid = s.create_strategy("A")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(Exception):
        s.import_version(sid, empty)


def test_import_version_v2_compares_and_appends_md(tmp_path):
    s = StrategyStore(root=tmp_path / "strategies")
    sid = s.create_strategy("测试策略")
    s.import_version(sid, write_report_dir(tmp_path, name="r1", total_return=-0.05))
    s.import_version(sid, write_report_dir(tmp_path, name="r2", total_return=-0.02))

    vdir = tmp_path / "strategies" / "1" / "versions" / "2"
    cmp = load(vdir / "comparison.json")
    assert cmp["comparable"] is True
    assert cmp["vs_v1"]["version"] == 1 and cmp["vs_v1"]["verdict"] == "progress"
    assert cmp["vs_prev"]["version"] == 1
    assert cmp["vs_v1"]["metrics_delta"]["total_return"]["delta"] == pytest.approx(0.03)

    md = (vdir / "report.md").read_text(encoding="utf-8")
    assert "## 版本对比" in md and "vs v1（原始版）" in md
    # 幂等：重跑 recompute 不重复追加
    s.recompute_comparison(sid, 2)
    assert (vdir / "report.md").read_text(encoding="utf-8").count("## 版本对比") == 1
    assert s.get_strategy(sid)["latest_version"] == 2


def test_import_version_not_comparable_notes(tmp_path):
    s = StrategyStore(root=tmp_path / "strategies")
    sid = s.create_strategy("A")
    s.import_version(sid, write_report_dir(tmp_path, name="r1", adjust="forward"))
    s.import_version(sid, write_report_dir(tmp_path, name="r2", adjust="backward"))
    cmp = load(tmp_path / "strategies" / "1" / "versions" / "2" / "comparison.json")
    assert cmp["comparable"] is False
    assert "复权口径" in cmp["note"]


def test_list_versions_order_and_get(tmp_path):
    s = StrategyStore(root=tmp_path / "strategies")
    sid = s.create_strategy("A")
    s.import_version(sid, write_report_dir(tmp_path, name="r1", total_return=-0.05))
    s.import_version(sid, write_report_dir(tmp_path, name="r2", total_return=-0.02))
    rows = s.list_versions(sid)
    assert [r["version"] for r in rows] == [1, 2]
    assert rows[1]["verdict"] == "progress"
    v2 = s.get_version(sid, 2)
    assert v2["version"] == 2
    with pytest.raises(VersionNotFoundError):
        s.get_version(sid, 9)
    assert s.get_comparison(sid, 1) is None
    assert s.get_comparison(sid, 2)["comparable"] is True


def test_atomic_write_no_tmp_left(tmp_path):
    s = StrategyStore(root=tmp_path / "strategies")
    s.create_strategy("A")
    sid = s.create_strategy("B")
    s.import_version(sid, write_report_dir(tmp_path, name="r1"))
    leftovers = [p for p in (tmp_path / "strategies").rglob("*.tmp")]
    assert leftovers == []
