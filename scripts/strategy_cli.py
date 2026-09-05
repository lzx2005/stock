"""策略模块 CLI：管理策略列表与版本，登记回测记录并做跨版本对比。

策略研究流程（配合回测专家 skill）：
    list 看已有策略 → 继续优化某策略时 record（版本递增 + 自动对比 v1 和上一版）
    全新策略 → create（记下 id），跑完回测后 record。

用法（项目根目录）：
    .venv/bin/python scripts/strategy_cli.py list
    .venv/bin/python scripts/strategy_cli.py create --name "双均线金叉+ATR止损" --desc "..."
    .venv/bin/python scripts/strategy_cli.py record --id 1 --from reports/双均线-20260831-143002 --note "增加 ATR 止损"
    .venv/bin/python scripts/strategy_cli.py compare --id 1 --version 2
    .venv/bin/python scripts/strategy_cli.py show --id 1
    .venv/bin/python scripts/strategy_cli.py versions --id 1
    .venv/bin/python scripts/strategy_cli.py show-version --id 1 --version 2
    .venv/bin/python scripts/strategy_cli.py rename --id 1 --name "新名"
    .venv/bin/python scripts/strategy_cli.py delete --id 1 --yes
"""
import argparse
import json
import sys

from strategy import StrategyStore
from strategy.compare import verdict_label
from strategy.store import _fmt_metric


def _fmt_pct(x):
    return f"{x:+.2%}" if isinstance(x, (int, float)) else "—"


def _fmt_num(x, nd=2):
    if x is None:
        return "—"
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def _print_comparison(cmp):
    if not cmp or not cmp.get("comparable"):
        print(f"  （不可比：{cmp.get('note', '无基线') if cmp else '无对比'}）")
        return
    for key, label in (("vs_v1", "vs v1"), ("vs_prev", "vs 上一版")):
        c = cmp.get(key)
        if not c:
            continue
        if not c.get("comparable"):
            print(f"  {label}（版本 {c.get('version')}）：不可比（{c.get('note', '')}）")
            continue
        print(f"  {label}（版本 {c.get('version')}）：{verdict_label(c.get('verdict'))}")


def cmd_create(s, args):
    sid = s.create_strategy(args.name, args.desc)
    print(f"已创建策略 #{sid}：{args.name}（最新版本 0，下次 record 升为 1）")


def cmd_list(s, args):
    rows = s.list_strategies()
    if not rows:
        print("（策略库为空。用 create 新建一个策略。）")
        return
    hdr = f"{'id':>3}  {'名称':<24} {'ver':>3}  {'总收益':>8} {'夏普':>6}  结论"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        latest = r.get("latest") or {}
        m = latest.get("metrics") or {}
        verdict = latest.get("verdict")
        verdict_str = verdict_label(verdict) if verdict else ("—" if r["latest_version"] else "无回测")
        print(f"{r['id']:>3}  {r['name'][:24]:<24} {r['latest_version']:>3}  "
              f"{_fmt_pct(m.get('total_return')):>8} {_fmt_num(m.get('sharpe')):>6}  {verdict_str}")


def cmd_show(s, args):
    info = s.get_strategy(args.id)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    print("\n版本列表：")
    for v in s.list_versions(args.id):
        m = v.get("metrics") or {}
        verdict = verdict_label(v.get("verdict")) if v.get("verdict") else "—"
        print(f"  v{v['version']}  {_fmt_pct(m.get('total_return'))}  dd={m.get('max_drawdown', '—')}  "
              f"sharpe={m.get('sharpe', '—')}  trades={m.get('trade_count', '—')}  {verdict}")


def cmd_versions(s, args):
    rows = s.list_versions(args.id)
    if not rows:
        print(f"策略 #{args.id} 还没有版本（record 第一个回测即 v1）")
        return
    for v in rows:
        m = v.get("metrics") or {}
        verdict = verdict_label(v.get("verdict")) if v.get("verdict") else "—"
        print(f"v{v['version']}  {_fmt_pct(m.get('total_return'))}  sharpe={m.get('sharpe', '—')}  "
              f"trades={m.get('trade_count', '—')}  {verdict}  {v.get('change_note') or ''}")


def cmd_show_version(s, args):
    v = s.get_version(args.id, args.version)
    print(json.dumps(v, ensure_ascii=False, indent=2))


def cmd_record(s, args):
    nv = s.import_version(args.id, args.from_dir, change_note=args.note)
    print(f"已登记策略 #{args.id} 版本 {nv}（产物复制自 {args.from_dir}）")
    if nv >= 2:
        cmp = s.get_comparison(args.id, nv)
        print("版本对比：")
        _print_comparison(cmp)
    else:
        print("v1（原始版）：无对比基线，后续版本将自动对比本版与上一版")


def cmd_compare(s, args):
    cmp = s.recompute_comparison(args.id, args.version)
    if cmp is None:
        print(f"v{args.version} 无对比基线（v1 不回比）")
        return
    print(f"策略 #{args.id} v{args.version} 对比：")
    _print_comparison(cmp)


def cmd_rename(s, args):
    s.rename_strategy(args.id, args.name)
    print(f"已改名：策略 #{args.id} → {args.name}")


def cmd_delete(s, args):
    if not args.yes:
        sys.exit("删除不可逆，需加 --yes 确认")
    s.delete_strategy(args.id)
    print(f"已删除策略 #{args.id}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="策略模块 CLI（策略列表/版本/回测登记/对比）")
    ap.add_argument("--root", default="data/strategies", help="策略库根目录（默认 data/strategies）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create", help="新建策略（记下 id 供 record 用）")
    p.add_argument("--name", required=True, help="策略名称")
    p.add_argument("--desc", default="", help="策略方案/需求描述")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("list", help="策略列表（含最新版指标与结论）")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="策略详情 + 版本一览")
    p.add_argument("--id", type=int, required=True)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("versions", help="版本列表")
    p.add_argument("--id", type=int, required=True)
    p.set_defaults(func=cmd_versions)

    p = sub.add_parser("show-version", help="版本详情（含回测决定参数/结果/方案）")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--version", type=int, required=True)
    p.set_defaults(func=cmd_show_version)

    p = sub.add_parser("record", help="把一次已完成回测登记为新版本（自动对比 v1+上一版）")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--from", dest="from_dir", required=True, help="回测产物目录（reports/ 或版本目录）")
    p.add_argument("--note", default="", help="相对上一版的改动说明")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("compare", help="重算版本对比（幂等）")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--version", type=int, required=True)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("rename", help="策略改名")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_rename)

    p = sub.add_parser("delete", help="删除策略（整棵，需 --yes）")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_delete)

    args = ap.parse_args(argv)
    args.func(StrategyStore(args.root), args)


if __name__ == "__main__":
    main()
