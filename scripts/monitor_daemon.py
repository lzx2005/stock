"""盯盘守护进程入口（前台运行，Ctrl-C 退出）。

用法（项目根目录；TICKFLOW_API_KEY 需已在环境中，先 source ~/.zshrc）：
    .venv/bin/python scripts/monitor_daemon.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))  # 防本文件遮蔽 monitor 包

from datacenter import DataCenter
from factors import FactorStore
import factors.factors  # noqa: F401 注册内置因子

from monitor import notify
from monitor.daemon import MonitorDaemon
from monitor.store import MonitorStore

DB_PATH = "data/monitor.db"


def main() -> None:
    dc = DataCenter()
    fs = FactorStore(dc)
    store = MonitorStore(DB_PATH)
    daemon = MonitorDaemon(store, dc, fs)

    tasks = store.list_tasks()
    enabled = sum(1 for t in tasks if t["enabled"])
    bark = "已配置" if notify.load_config().get("bark_key") else "未配置（仅记录信号，不推送）"
    print(f"[monitor] 盯盘守护进程启动 db={DB_PATH}")
    print(f"[monitor] 任务数={len(tasks)}（启用 {enabled}）  Bark={bark}")
    daemon.run()


if __name__ == "__main__":
    main()
