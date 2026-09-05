import sqlite3
import time
from pathlib import Path

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    script TEXT NOT NULL,
    interval_sec INTEGER NOT NULL DEFAULT 60,
    enabled INTEGER NOT NULL DEFAULT 1,
    notify INTEGER NOT NULL DEFAULT 1,
    buy_on INTEGER NOT NULL DEFAULT 0,
    sell_on INTEGER NOT NULL DEFAULT 0,
    poll_count INTEGER NOT NULL DEFAULT 0,
    signal_count INTEGER NOT NULL DEFAULT 0,
    last_run_at INTEGER,
    error_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    kind TEXT NOT NULL,
    price REAL,
    message TEXT
);
"""

_LAMP_FIELDS = ("buy_on", "sell_on")

_UPDATE_FIELDS = ("name", "symbol", "script", "interval_sec", "notify")


class MonitorStore:
    """SQLite 盯盘存储：tasks（任务+灯状态一行）、signals（边沿信号历史）。
    WAL 模式支持多读单写；建表幂等，可重复初始化。"""

    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self):
        self._conn.close()

    # ---- tasks ----
    def add_task(self, name: str, symbol: str, script: str,
                 interval_sec: int = 60, notify: int = 1) -> int:
        cur = self._conn.execute(
            "INSERT INTO tasks (name, symbol, script, interval_sec, notify, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (name, symbol, script, interval_sec, notify, int(time.time() * 1000)))
        self._conn.commit()
        return cur.lastrowid

    def list_tasks(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def update_task(self, task_id: int, *, name=None, symbol=None,
                    script=None, interval_sec=None, notify=None) -> None:
        """只更新非 None 的字段；全为 None 时不执行任何 SQL。"""
        values = {"name": name, "symbol": symbol, "script": script,
                  "interval_sec": interval_sec, "notify": notify}
        sets, args = [], []
        for field in _UPDATE_FIELDS:
            if values[field] is not None:
                sets.append(f"{field}=?")
                args.append(values[field])
        if not sets:
            return
        args.append(task_id)
        self._conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", args)
        self._conn.commit()

    def set_enabled(self, task_id: int, enabled: int) -> None:
        self._conn.execute(
            "UPDATE tasks SET enabled=? WHERE id=?", (enabled, task_id))
        self._conn.commit()

    def delete_task(self, task_id: int) -> None:
        self._conn.execute("DELETE FROM signals WHERE task_id=?", (task_id,))
        self._conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self._conn.commit()

    def bump_poll(self, task_id: int, ts_ms: int) -> None:
        """轮询计数 +1 并记录上次执行时间（ms）。"""
        self._conn.execute(
            "UPDATE tasks SET poll_count=poll_count+1, last_run_at=? WHERE id=?",
            (ts_ms, task_id))
        self._conn.commit()

    def record_error(self, task_id: int, message: str) -> None:
        self._conn.execute(
            "UPDATE tasks SET error_count=error_count+1, last_error=? WHERE id=?",
            (message, task_id))
        self._conn.commit()

    def set_lamp(self, task_id: int, field: str, value: int) -> None:
        """原子更新灯状态；field 白名单校验防注入。"""
        if field not in _LAMP_FIELDS:
            raise ValueError(f"非法灯字段: {field!r}，仅允许 {_LAMP_FIELDS}")
        self._conn.execute(
            f"UPDATE tasks SET {field}=? WHERE id=?", (value, task_id))
        self._conn.commit()

    # ---- signals ----
    def add_signal(self, task_id: int, ts_ms: int, kind: str,
                   price: float | None, message: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO signals (task_id, ts, kind, price, message) VALUES (?,?,?,?,?)",
            (task_id, ts_ms, kind, price, message))
        self._conn.execute(
            "UPDATE tasks SET signal_count=signal_count+1 WHERE id=?", (task_id,))
        self._conn.commit()
        return cur.lastrowid

    def list_signals(self, task_id: int | None = None, limit: int = 200) -> list[dict]:
        """按 ts 倒序；task_id 为 None 时跨任务取最近 limit 条。"""
        if task_id is None:
            rows = self._conn.execute(
                "SELECT * FROM signals ORDER BY ts DESC, id DESC LIMIT ?",
                (limit,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM signals WHERE task_id=? ORDER BY ts DESC, id DESC LIMIT ?",
                (task_id, limit)).fetchall()
        return [dict(r) for r in rows]
