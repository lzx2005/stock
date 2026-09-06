"""盯盘调度守护进程：交易时段内按周期轮询任务、判定信号灯边沿并推送通知。

- 交易时段（北京本地时间）：9:25~11:30、13:00~15:00；非交易时段 tick 直接返回。
- 每轮 tick 重读 tasks（start/stop 立即生效）；最小调度粒度 60s。
- DataError / 取数空 → 静默跳过（休市/停牌，不记错误）；其他异常 → record_error，任务隔离。
- 灯边沿才写信号并推送：「灯亮」「灯灭」，条件持续满足不重复通知。
"""

import time

from monitor import notify
from monitor.runtime import DataError, MonitorContext, run_check

# 北京时间交易时段（分钟数，含端点）：9:25~11:30、13:00~15:00
_TRADING_WINDOWS = ((9 * 60 + 25, 11 * 60 + 30), (13 * 60, 15 * 60))


def edge_transition(old: int, new) -> str | None:
    """判定信号灯边沿。

    new is None → None；new=True 且 old=0 → "on"；
    new=False 且 old=1 → "off"；否则 None。
    """
    if new is None:
        return None
    if new is True and not old:
        return "on"
    if new is False and old:
        return "off"
    return None


def in_trading_hours(ts_ms: int) -> bool:
    """ts_ms 是否处于北京交易时段（9:25~11:30 或 13:00~15:00，本地时区即北京）。"""
    t = time.localtime(ts_ms / 1000)
    minutes = t.tm_hour * 60 + t.tm_min
    return any(start <= minutes <= end for start, end in _TRADING_WINDOWS)


class MonitorDaemon:
    """盯盘主循环：tick() 单轮调度；run() 无限循环，按分钟边界对齐休眠。"""

    def __init__(self, store, dc, fs, send_fn=notify.send,
                 interval_default: int = 60):
        self.store = store
        self.dc = dc
        self.fs = fs
        self.send_fn = send_fn
        self.interval_default = interval_default

    def tick(self, now_ms: int | None = None) -> None:
        """单轮调度：非交易时段直接返回；到期任务执行 check 并做边沿判定。"""
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        if not in_trading_hours(now):
            return
        for task in self.store.list_tasks():
            if not task["enabled"]:
                continue
            interval_ms = max(60, task["interval_sec"] or self.interval_default) * 1000
            if (now - (task["last_run_at"] or 0)) < interval_ms:
                continue
            self._run_task(task, now)

    def _run_task(self, task: dict, now_ms: int) -> None:
        tid = task["id"]
        ctx = MonitorContext(self.dc, self.fs, task["symbol"], asof_ms=now_ms)
        try:
            out = run_check(task["script"], ctx)
        except DataError:
            return  # 无当日数据：静默跳过，不记错误
        except Exception as e:
            self.store.record_error(tid, str(e))
            return
        self.store.bump_poll(tid, now_ms)
        edge = edge_transition(task["lamp_on"], out["on"])
        if edge is None:
            return
        self.store.set_lamp(tid, "lamp_on", 1 if out["on"] else 0)
        price = None
        try:
            price = ctx.price()
        except Exception:
            pass  # 取价失败不阻断：信号照常写入，price 记 None
        msg = out["msg"] or ""
        self.store.add_signal(tid, now_ms, edge, price, msg)
        if task["notify"]:
            try:
                ok = self.send_fn(self._format_message(
                    task["name"], out["on"], msg, now_ms))
            except Exception:
                ok = False
            if not ok:
                self.store.record_error(tid, "bark 推送失败")

    @staticmethod
    def _format_message(name: str, on: bool, msg: str, ts_ms: int) -> str:
        state = "亮" if on else "灭"
        t = time.localtime(ts_ms / 1000)
        ts = time.strftime("%Y-%m-%d %H:%M", t)
        return f"【盯盘】{name} 灯{state}：{msg}（{ts}）"

    def run(self) -> None:
        """无限主循环：每轮 tick 后 sleep 到下一分钟边界。

        tick 级意外异常（如 sqlite OperationalError）打印堆栈并继续，
        不让守护进程因单轮故障退出。
        """
        while True:
            try:
                self.tick()
            except Exception:
                import traceback
                traceback.print_exc()
                time.sleep(60)
                continue
            time.sleep(60 - time.time() % 60)
