#!/usr/bin/env python3
"""回测专家 · 报告生成器。

输入：回测工作目录（含 results.json + equity.csv）
输出：同目录 回测报告.pdf（reportlab 排版 + matplotlib 模拟收益图）+ equity_curve.png

用法：
    source ~/.zshrc
    .venv/bin/python .claude/skills/backtest-expert/scripts/build_report.py <report目录>

results.json schema（由 SKILL.md 工作流程 Step4/Step5 写入）：
{
  "strategy_name": "双均线(5/20)",
  "requirement": "用户需求原话",
  "assumptions": ["假设清单..."],
  "symbols": ["600000.SH"],
  "period": "1d",
  "start": "2023-08-31", "end": "2026-08-31",
  "initial_cash": 1000000,
  "strategy_logic": "策略逻辑一句话",
  "matching": "撮合规则描述",
  "metrics": {"total_return":..., "annual_return":..., "max_drawdown":...,
              "sharpe":..., "trade_count":..., "win_rate":...,
              "profit_loss_ratio":..., "final_equity":...},
  "benchmark": {"name": "买入持有", "total_return": 0.05},
  "trades": [{"symbol":..., "buy_date":..., "buy_price":..., "sell_date":...,
              "sell_price":..., "shares":..., "pnl":...}],
  "entry_exit": {"strategy": "...", "entry": "...", "exit": "...", "conditions": "..."}
}

equity.csv：timestamp(ms),equity[,benchmark]（可无 benchmark 列）。
"""

import json
import os
import sys

UP = "#E23B33"
DOWN = "#0FA67C"
INK = "#1F2430"
MUTED = "#6B7787"
GRID = "#E4E9F0"


# ---------------- 中文字体（matplotlib 画图 + reportlab 排版） ----------------

def _pick_matplotlib_family():
    import matplotlib.font_manager as fm
    cands = [
        "PingFang SC", "Hiragino Sans GB", "STHeiti", "Songti SC", "Heiti SC",
        "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Zen Hei",
    ]
    have = {f.name for f in fm.fontManager.ttflist}
    for c in cands:
        if c in have:
            return c
    for p in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "C:/Windows/Fonts/msyh.ttc",
    ):
        if os.path.exists(p):
            try:
                fm.fontManager.addfont(p)
                return fm.FontProperties(fname=p).get_name()
            except Exception:
                continue
    return None


def _register_reportlab_font():
    """优先注册系统 TTF/TTC（效果好），失败则退回内置 CID 中文（STSong-Light）。"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for name, path in (
        ("CJK", "/System/Library/Fonts/PingFang.ttc"),
        ("CJK", "/System/Library/Fonts/Hiragino Sans GB.ttc"),
        ("CJK", "/System/Library/Fonts/STHeiti Medium.ttc"),
        ("CJK", "/System/Library/Fonts/Supplemental/Songti.ttc"),
        ("CJK", "C:/Windows/Fonts/msyh.ttc"),
    ):
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0))
                pdfmetrics.registerFont(TTFont(name + "-Bold", path, subfontIndex=0))
                return name, name + "-Bold"
            except Exception:
                continue
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        return "STSong-Light", "STSong-Light"
    except Exception as e:
        sys.exit(f"无法注册中文字体: {e}")


# ---------------- 工具 ----------------


def pct(x):
    return f"{x:+.2%}" if x is not None else "—"


def money(x):
    if x is None:
        return "—"
    if abs(x) >= 1e8:
        return f"{x / 1e8:,.2f} 亿"
    if abs(x) >= 1e4:
        return f"{x / 1e4:,.1f} 万"
    return f"{x:,.0f}"


# ---------------- 版本对比章节（可选） ----------------

_CMP_PCT = {"total_return", "excess_return", "annual_return", "max_drawdown", "win_rate"}
_CMP_MONEY = {"final_equity"}
_CMP_VERDICT = {"progress": "进步", "regress": "退步", "mixed": "部分改善"}


def _fmt_cmp(name, x):
    if x is None:
        return "—"
    try:
        f = float(x)
    except (TypeError, ValueError):
        return "—"
    if name in _CMP_PCT:
        return f"{f:+.2%}"
    if name in _CMP_MONEY:
        return money(f)
    if name == "trade_count":
        return f"{int(f)}"
    return f"{f:.2f}"


def _comparison_flowables(report_dir, cjk, cjk_bold):
    """读 comparison.json → 版本对比章节 flowables。文件缺失/损坏返回 None（保持原 6 章）。"""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    cpath = os.path.join(report_dir, "comparison.json")
    if not os.path.exists(cpath):
        return None
    try:
        with open(cpath, encoding="utf-8") as f:
            C = json.load(f)
    except (OSError, ValueError):
        return None

    body = ParagraphStyle("cmpbody", fontName=cjk, fontSize=10, leading=15, spaceAfter=4)
    cell = ParagraphStyle("cmpcell", fontName=cjk, fontSize=8.5, leading=12)
    cell_b = ParagraphStyle("cmpcellb", fontName=cjk_bold, fontSize=8.5, leading=12)
    small = ParagraphStyle("cmpsmall", fontName=cjk, fontSize=8.5, leading=12, textColor=MUTED)

    flow = []
    if not C.get("comparable"):
        flow.append(Paragraph(f"<b>本版与基线回测设置不一致，无法对比：</b>{C.get('note', '')}", small))
        return flow
    for key, label in (("vs_v1", "vs v1（原始版）"), ("vs_prev", "vs 上一版")):
        c = C.get(key)
        if not c:
            continue
        if not c.get("comparable"):
            flow.append(Paragraph(f"<b>{label}（版本 {c.get('version')}）：</b>不可比（{c.get('note', '')}）", small))
            continue
        verdict = _CMP_VERDICT.get(c.get("verdict"), c.get("verdict"))
        flow.append(Paragraph(f"<b>{label}（版本 {c.get('version')}）：{verdict}</b>", body))
        rows = [[Paragraph(x, cell_b) for x in ["指标", "基准版值", "本版值", "差值", "方向"]]]
        for name, d in c.get("metrics_delta", {}).items():
            arrow = {True: "↑", False: "↓", None: "—"}.get(d.get("better"), "—")
            rows.append([
                Paragraph(name, cell),
                Paragraph(_fmt_cmp(name, d.get("old")), cell),
                Paragraph(_fmt_cmp(name, d.get("new")), cell),
                Paragraph(_fmt_cmp(name, d.get("delta")), cell),
                Paragraph(arrow, cell),
            ])
        t = Table(rows, colWidths=[42 * mm, 34 * mm, 34 * mm, 34 * mm, 16 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8FB")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        flow.append(t)
        flow.append(Spacer(1, 8))
    return flow


# ---------------- 模拟收益图（matplotlib） ----------------


def draw_equity_curve(report_dir, family):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    if family:
        plt.rcParams["font.family"] = [family]
    plt.rcParams["axes.unicode_minus"] = False

    csv_path = os.path.join(report_dir, "equity.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"缺少 equity.csv: {csv_path}")
    df = pd.read_csv(csv_path)
    df = df.dropna(subset=["equity"])
    if df.empty or len(df) < 2:
        # 无足够点：画占位图说明
        fig, ax = plt.subplots(figsize=(9, 3.6), dpi=130)
        ax.text(0.5, 0.5, "该区间权益曲线点过少（可能未触发交易）",
                ha="center", va="center", fontsize=13, color=MUTED)
        ax.axis("off")
        out = os.path.join(report_dir, "equity_curve.png")
        fig.savefig(out, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return out

    dt = pd.to_datetime(df["timestamp"], unit="ms")
    base = df["equity"].iloc[0]
    norm = df["equity"] / base * 100

    fig, ax = plt.subplots(figsize=(9, 4), dpi=130)
    ax.fill_between(dt, norm, norm.min() - (norm.max() - norm.min()) * 0.06,
                    color=UP, alpha=0.07, zorder=1)
    ax.plot(dt, norm, color=UP, lw=1.8, zorder=2, label="策略")

    if "benchmark" in df.columns and df["benchmark"].notna().sum() > 1:
        bnorm = df["benchmark"] / df["benchmark"].iloc[0] * 100
        ax.plot(dt, bnorm, color=MUTED, lw=1.3, ls="--", zorder=2, label="基准")

    ax.set_title("模拟收益（权益曲线，初始 = 100）", fontsize=13, fontweight="bold", color=INK)
    ax.set_ylabel("净值", fontsize=11, color=INK)
    ax.grid(True, color=GRID, lw=0.6, alpha=0.8)
    ax.axhline(100, color=GRID, lw=1.0, zorder=1)
    ax.legend(frameon=False, fontsize=10)
    ax.tick_params(colors=INK, labelsize=9)
    for sp in ax.spines.values():
        sp.set_color(GRID)

    out = os.path.join(report_dir, "equity_curve.png")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


# ---------------- PDF 组装（reportlab） ----------------


def build_pdf(report_dir, cjk, cjk_bold, chart_png):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)
    from reportlab.lib.enums import TA_LEFT, TA_CENTER

    with open(os.path.join(report_dir, "results.json"), encoding="utf-8") as f:
        R = json.load(f)

    m = R.get("metrics", {})
    bench = R.get("benchmark", {})
    ee = R.get("entry_exit", {})
    trades = R.get("trades", [])

    W, H = A4
    doc = SimpleDocTemplate(os.path.join(report_dir, "回测报告.pdf"), pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"回测专家报告 · {R.get('strategy_name', '')}")

    styles = getSampleStyleSheet()
    def st(name, size, leading, space_before=0, space_after=0, color=INK,
           align=TA_LEFT, bold=False, **kw):
        return ParagraphStyle(name, fontName=(cjk_bold if bold else cjk),
                              fontSize=size, leading=leading, textColor=color,
                              spaceBefore=space_before, spaceAfter=space_after,
                              alignment=align, **kw)

    title = st("title", 20, 26, 6, 16, bold=True, align=TA_CENTER)
    sub = st("sub", 10, 14, 0, 18, MUTED, align=TA_CENTER)
    h = st("h", 13, 18, 12, 6, bold=True)
    h.spaceBefore = 18
    body = st("body", 10, 15, 0, 4)
    small = st("small", 8.5, 12, 0, 2, MUTED)
    cell = st("cell", 9, 13, 0, 0)
    cell_b = st("cellb", 9, 13, 0, 0, bold=True)

    flow = []
    flow.append(Paragraph(f"回测专家报告 · {R.get('strategy_name', '')}", title))
    flow.append(Paragraph(f"回测区间 {R.get('start', '?')} ~ {R.get('end', '?')} ｜ 标的 {', '.join(R.get('symbols', []))} ｜ 周期 {R.get('period', '')}", sub))

    # 一、回测内容
    flow.append(Paragraph("一、回测内容", h))
    flow.append(Paragraph(f"<b>用户需求：</b>{R.get('requirement', '')}", body))
    for i, a in enumerate(R.get("assumptions", []), 1):
        flow.append(Paragraph(f"假设 {i}：{a}", small))
    flow.append(Spacer(1, 4))

    # 二、回测方法
    flow.append(Paragraph("二、回测方法", h))
    flow.append(Paragraph(f"<b>策略逻辑：</b>{R.get('strategy_logic', '')}", body))
    flow.append(Paragraph(f"<b>撮合规则：</b>{R.get('matching', '')}", body))
    flow.append(Paragraph(f"<b>初始资金：</b>{money(R.get('initial_cash'))}", body))

    # 三、回测结果
    flow.append(Paragraph("三、回测结果", h))
    def r(metric, name):
        return [name, m.get(metric)]
    rows = [
        [Paragraph("指标", cell_b), Paragraph("策略", cell_b),
         Paragraph(f"基准（{bench.get('name', '—')}）", cell_b)],
        ["期末权益", money(m.get("final_equity")), "—"],
        ["总收益", pct(m.get("total_return")), pct(bench.get("total_return"))],
        ["年化收益", pct(m.get("annual_return")), "—"],
        ["最大回撤", pct(m.get("max_drawdown")), "—"],
        ["夏普比率", f"{m.get('sharpe', 0):.2f}" if m.get("sharpe") is not None else "—", "—"],
        ["交易次数", str(m.get("trade_count", 0)), "—"],
        ["胜率", pct(m.get("win_rate")), "—"],
        ["盈亏比", f"{m.get('profit_loss_ratio', 0):.2f}" if m.get("profit_loss_ratio") is not None else "—", "—"],
    ]
    t = Table(rows, colWidths=[52 * mm, 44 * mm, 48 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8FB")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("FONTNAME", (0, 1), (-1, -1), cjk),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 6))

    # 四、模拟收益图
    flow.append(Paragraph("四、模拟收益图", h))
    flow.append(Image(chart_png, width=178 * mm, height=178 * mm * (4 / 9)))

    # 五、交易明细
    flow.append(Paragraph("五、交易明细", h))
    recent = list(reversed(trades[-20:])) if trades else []
    if recent:
        hdr = [Paragraph(x, cell_b) for x in ["买入日期", "标的", "买入价", "卖出日期", "卖出价", "股数", "盈亏"]]
        trows = [hdr]
        for tr in recent:
            trows.append([
                Paragraph(tr.get("buy_date", ""), cell),
                Paragraph(tr.get("symbol", ""), cell),
                Paragraph(f"{tr.get('buy_price', 0):.2f}", cell),
                Paragraph(tr.get("sell_date", ""), cell),
                Paragraph(f"{tr.get('sell_price', 0):.2f}", cell),
                Paragraph(money(tr.get("shares", 0)), cell),
                Paragraph(f"{tr.get('pnl', 0):+,.0f}", cell),
            ])
        tt = Table(trows, colWidths=[30 * mm, 26 * mm, 20 * mm, 30 * mm, 20 * mm, 24 * mm, 26 * mm])
        tt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8FB")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("FONTNAME", (0, 1), (-1, -1), cjk),
        ]))
        flow.append(tt)
        flow.append(Paragraph(f"共 {m.get('trade_count', 0)} 个已平仓回合，仅列出最近 {len(recent)} 笔", small))
    else:
        flow.append(Paragraph("该区间没有已平仓交易（可能未触发买入/卖出信号）。", body))

    # 六、操作指引
    flow.append(Paragraph("六、操作指引", h))
    guide = [
        ("选股策略", ee.get("strategy", "—")),
        ("进场时机", ee.get("entry", "—")),
        ("出场时机", ee.get("exit", "—")),
        ("同花顺一句话条件", ee.get("conditions", "—")),
    ]
    for k, v in guide:
        flow.append(Paragraph(f"<b>{k}：</b>{v}", body))

    # 七、版本对比（可选：版本目录存在 comparison.json 才渲染，向后兼容老 reports/）
    cmp_flow = _comparison_flowables(report_dir, cjk, cjk_bold)
    if cmp_flow:
        flow.append(Paragraph("七、版本对比", h))
        flow.extend(cmp_flow)
    flow.append(Spacer(1, 6))
    flow.append(Paragraph("免责声明：本报告基于本地已存历史数据与默认成本模型（含佣金/印花税/滑点，T+1 撮合），"
                          "用于验证假设，不代表未来收益，不构成投资建议。", small))

    doc.build(flow)
    return os.path.join(report_dir, "回测报告.pdf")


def main():
    if len(sys.argv) != 2:
        sys.exit("用法: build_report.py <report目录>")
    report_dir = sys.argv[1]
    if not os.path.isdir(report_dir):
        sys.exit(f"不是目录: {report_dir}")

    family = _pick_matplotlib_family()
    if family:
        print(f"[matplotlib] 中文字体: {family}")
    else:
        print("[matplotlib] 警告: 未找到中文字体，图表中文可能显示为方块")
    cjk, cjk_bold = _register_reportlab_font()
    print(f"[reportlab] 中文字体: {cjk}")

    chart_png = draw_equity_curve(report_dir, family)
    print(f"[chart] {chart_png}")
    pdf = build_pdf(report_dir, cjk, cjk_bold, chart_png)
    print(f"[pdf] {pdf}")


if __name__ == "__main__":
    main()
