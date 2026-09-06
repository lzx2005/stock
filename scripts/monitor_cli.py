"""盯盘任务管理 CLI：register/list/show/toggle/delete，供人工与 skill 调用。

用法（项目根目录）：
    .venv/bin/python scripts/monitor_cli.py register --name N --symbol S \
        [--interval 60] [--no-notify] [--description "原理/实现/回放结果"] \
        --script-file path.py   # → 打印 task_id=
    .venv/bin/python scripts/monitor_cli.py list              # id/灯/名称/symbol/interval/enabled/notify/错误
    .venv/bin/python scripts/monitor_cli.py show <id>         # 详情 + script 全文
    .venv/bin/python scripts/monitor_cli.py toggle <id>       # enabled 翻转，打印新状态
    .venv/bin/python scripts/monitor_cli.py delete <id> --yes
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))  # 防 scripts/ 下同名脚本遮蔽 monitor 包

from monitor.store import MonitorStore

DEFAULT_DB = "data/monitor.db"


def _lamp(task: dict) -> str:
    """灯状态：亮 ● 灭 ○。"""
    return "●" if task["lamp_on"] else "○"


def _cmd_register(store: MonitorStore, args) -> None:
    script = Path(args.script_file).read_text(encoding="utf-8")
    notify = 0 if args.no_notify else 1
    task_id = store.add_task(args.name, args.symbol, script,
                             interval_sec=args.interval, notify=notify,
                             description=args.description or "")
    print(f"task_id={task_id}")


def _cmd_list(store: MonitorStore, _args) -> None:
    tasks = store.list_tasks()
    print(f"{'id':<4} {'灯':<8} {'名称':<12} {'symbol':<12} {'interval':>8} "
          f"{'enabled':>7} {'notify':>6}  错误")
    for t in tasks:
        err = f"{t['error_count']}"
        if t["last_error"]:
            err += f"（{t['last_error'][:40]}）"
        print(f"{t['id']:<4} {_lamp(t):<8} {t['name']:<12} {t['symbol']:<12} "
              f"{t['interval_sec']:>8} {t['enabled']:>7} {t['notify']:>6}  {err}")


def _cmd_show(store: MonitorStore, args) -> None:
    t = store.get_task(args.id)
    if t is None:
        print(f"任务 {args.id} 不存在")
        return
    print(f"id={t['id']}  名称={t['name']}  symbol={t['symbol']}")
    print(f"interval={t['interval_sec']}s  enabled={t['enabled']}  notify={t['notify']}")
    print(f"灯={_lamp(t)}  轮询={t['poll_count']}  信号={t['signal_count']}  "
          f"错误={t['error_count']}  last_error={t['last_error'] or '—'}")
    if t.get("description"):
        print(f"--- description ---\n{t['description']}")
    print("--- script ---")
    print(t["script"])


def _cmd_toggle(store: MonitorStore, args) -> None:
    t = store.get_task(args.id)
    if t is None:
        print(f"任务 {args.id} 不存在")
        return
    new = 0 if t["enabled"] else 1
    store.set_enabled(args.id, new)
    print(f"任务 {args.id} enabled={new}")


def _cmd_delete(store: MonitorStore, args) -> None:
    if not args.yes:
        print("删除需加 --yes 确认")
        return
    store.delete_task(args.id)
    print(f"已删除任务 {args.id}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="monitor_cli", description="盯盘任务管理 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("register", help="注册盯盘任务")
    r.add_argument("--name", required=True)
    r.add_argument("--symbol", required=True)
    r.add_argument("--interval", type=int, default=60)
    r.add_argument("--no-notify", action="store_true")
    r.add_argument("--description", default="",
                   help="任务说明：盯盘原理/实现方式/回放结果，webui 列表悬停可见")
    r.add_argument("--script-file", required=True)
    r.set_defaults(func=_cmd_register)

    l = sub.add_parser("list", help="任务列表")
    l.set_defaults(func=_cmd_list)

    s = sub.add_parser("show", help="任务详情 + script 全文")
    s.add_argument("id", type=int)
    s.set_defaults(func=_cmd_show)

    t = sub.add_parser("toggle", help="enabled 翻转")
    t.add_argument("id", type=int)
    t.set_defaults(func=_cmd_toggle)

    d = sub.add_parser("delete", help="删除任务（需 --yes）")
    d.add_argument("id", type=int)
    d.add_argument("--yes", action="store_true")
    d.set_defaults(func=_cmd_delete)

    return p


def main(argv, db_path: str = DEFAULT_DB) -> None:
    args = _build_parser().parse_args(argv)
    store = MonitorStore(db_path)
    try:
        args.func(store, args)
    finally:
        store.close()


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
