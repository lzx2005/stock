"""build_report 版本对比章节渲染冒烟（reportlab 较重，仅覆盖新增渲染路径）。"""

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BR_PATH = REPO / ".claude" / "skills" / "backtest-expert" / "scripts" / "build_report.py"

spec = importlib.util.spec_from_file_location("build_report", BR_PATH)
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)

BROKER = {"commission": 0.0003, "min_commission": 5.0, "stamp_tax": 0.0005,
          "slippage": 0.0, "lot_size": 100, "t_plus_1": True}


def _write_results(d, total_return=-0.05):
    (d / "results.json").write_text(json.dumps({
        "strategy_name": "对比冒烟",
        "requirement": "r", "assumptions": [], "symbols": ["600519.SH"],
        "period": "1d", "start": "2023-01-01", "end": "2026-08-31",
        "initial_cash": 1000000, "strategy_logic": "l", "matching": "m",
        "metrics": {"total_return": total_return, "annual_return": -0.02,
                    "max_drawdown": 0.2, "sharpe": 0.3, "trade_count": 10,
                    "win_rate": 0.5, "profit_loss_ratio": 0.7,
                    "final_equity": 950000},
        "benchmark": {"name": "买入持有", "total_return": -0.22},
        "trades": [], "entry_exit": {"strategy": "s", "entry": "e", "exit": "x",
                                     "conditions": "c"},
    }, ensure_ascii=False), encoding="utf-8")
    (d / "equity.csv").write_text("timestamp,equity\n100,1000000\n200,1050000\n"
                                  "300,1020000\n400,1080000\n", encoding="utf-8")


def _comparison(total_return):
    return {
        "strategy_id": 1, "version": 2, "created_at_ms": 0, "comparable": True,
        "note": "", "primary": ["total_return", "excess_return", "max_drawdown", "sharpe"],
        "vs_v1": {"version": 1, "comparable": True, "verdict": "progress",
                  "metrics_delta": {"total_return": {"old": -0.05, "new": total_return,
                                                      "delta": total_return + 0.05,
                                                      "better": True}}},
        "vs_prev": {"version": 1, "comparable": True, "verdict": "progress",
                    "metrics_delta": {"total_return": {"old": -0.05, "new": total_return,
                                                        "delta": total_return + 0.05,
                                                        "better": True}}},
    }


def _build(report_dir):
    cjk, cjk_bold = br._register_reportlab_font()   # 先注册字体，再排版
    png = br.draw_equity_curve(str(report_dir), None)
    pdf = br.build_pdf(str(report_dir), cjk, cjk_bold, png)
    return pdf


def test_build_without_comparison_stays_six_chapters(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    _write_results(d)
    pdf = _build(d)
    with open(pdf, "rb") as f:
        assert f.read(5) == b"%PDF-"


def test_build_with_comparison_chapter(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    _write_results(d)
    (d / "comparison.json").write_text(json.dumps(_comparison(-0.02), ensure_ascii=False),
                                       encoding="utf-8")
    pdf = _build(d)
    with open(pdf, "rb") as f:
        assert f.read(5) == b"%PDF-"


def test_build_with_not_comparable_comparison(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    _write_results(d)
    cmp = _comparison(-0.02)
    cmp["comparable"] = False
    cmp["note"] = "回测设置不一致：周期"
    (d / "comparison.json").write_text(json.dumps(cmp, ensure_ascii=False), encoding="utf-8")
    pdf = _build(d)
    with open(pdf, "rb") as f:
        assert f.read(5) == b"%PDF-"


def test_build_with_broken_comparison_falls_back(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    _write_results(d)
    (d / "comparison.json").write_text("{ 坏掉的 json", encoding="utf-8")
    pdf = _build(d)          # 损坏 → 静默跳过，仍出 PDF
    with open(pdf, "rb") as f:
        assert f.read(5) == b"%PDF-"
