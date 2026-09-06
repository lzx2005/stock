import json
import sqlite3
import time
from pathlib import Path

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS kline_coverage (
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (symbol, period)
);
CREATE TABLE IF NOT EXISTS sync_jobs (
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,
    status TEXT NOT NULL,          -- done
    updated_at REAL NOT NULL,
    PRIMARY KEY (symbol, period)
);
CREATE TABLE IF NOT EXISTS instruments (
    symbol TEXT PRIMARY KEY,
    exchange TEXT NOT NULL,
    code TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS universe_members (
    universe_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    added_at REAL NOT NULL,
    PRIMARY KEY (universe_id, symbol)
);
CREATE TABLE IF NOT EXISTS ex_factors (
    symbol TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    ex_factor REAL NOT NULL,
    PRIMARY KEY (symbol, ts_ms)
);
CREATE TABLE IF NOT EXISTS meta_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


class MetaStore:
    """SQLite 元数据：K线覆盖区间、回填进度、标的清单。WAL 模式支持多读单写。"""

    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._migrate_instruments()
        self._migrate_job_reports()

    def _migrate_instruments(self):
        """第一期的 instruments 表只有 3 列，Task 5 扩列：ALTER TABLE 兼容旧库。"""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(instruments)")}
        for col in ("name", "type", "region", "ext_json"):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE instruments ADD COLUMN {col} TEXT")
        self._conn.commit()

    def _migrate_job_reports(self):
        """scripts/validate.py 早期版本建过不同 schema 的 job_reports，弃用重建。"""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(job_reports)")}
        if cols and "report_json" not in cols:
            self._conn.execute("DROP TABLE job_reports")
            self._conn.execute(
                "CREATE TABLE job_reports (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " job TEXT NOT NULL, report_json TEXT NOT NULL, created_at REAL NOT NULL)")
            self._conn.commit()

    def close(self):
        self._conn.close()

    # ---- coverage ----
    def get_coverage(self, symbol: str, period: str) -> tuple[int, int] | None:
        row = self._conn.execute(
            "SELECT start_ms, end_ms FROM kline_coverage WHERE symbol=? AND period=?",
            (symbol, period)).fetchone()
        return (row[0], row[1]) if row else None

    def extend_coverage(self, symbol: str, period: str, start_ms: int, end_ms: int) -> None:
        """语义：区间 [start_ms, end_ms] 表示"已向数据源请求并解析过的范围"，
        不是"有数据的范围"——空结果区间同样标记覆盖，防止反复回源打空。
        与既有覆盖取并集，不收缩。"""
        cov = self.get_coverage(symbol, period)
        if cov:
            start_ms, end_ms = min(cov[0], start_ms), max(cov[1], end_ms)
        self._conn.execute(
            "INSERT INTO kline_coverage (symbol, period, start_ms, end_ms, updated_at)"
            " VALUES (?,?,?,?,?) ON CONFLICT(symbol, period) DO UPDATE SET"
            " start_ms=excluded.start_ms, end_ms=excluded.end_ms, updated_at=excluded.updated_at",
            (symbol, period, start_ms, end_ms, time.time()))
        self._conn.commit()

    # ---- sync jobs ----
    def mark_done(self, symbol: str, period: str) -> None:
        self._conn.execute(
            "INSERT INTO sync_jobs (symbol, period, status, updated_at) VALUES (?,?, 'done', ?)"
            " ON CONFLICT(symbol, period) DO UPDATE SET status='done', updated_at=excluded.updated_at",
            (symbol, period, time.time()))
        self._conn.commit()

    def pending_symbols(self, symbols: list[str], period: str) -> list[str]:
        if not symbols:
            return []
        marks = ",".join("?" * len(symbols))
        done = {r[0] for r in self._conn.execute(
            f"SELECT symbol FROM sync_jobs WHERE period=? AND status='done' AND symbol IN ({marks})",
            (period, *symbols))}
        return [s for s in symbols if s not in done]

    # ---- instruments ----
    def upsert_symbols(self, symbols: list[str]) -> None:
        now = time.time()
        self._conn.executemany(
            "INSERT INTO instruments (symbol, exchange, code, updated_at) VALUES (?,?,?,?)"
            " ON CONFLICT(symbol) DO UPDATE SET updated_at=excluded.updated_at",
            [(s, s.split(".")[-1], s.split(".")[0], now) for s in symbols])
        self._conn.commit()

    def symbol_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]

    def all_symbols(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT symbol FROM instruments ORDER BY symbol")]

    def upsert_instruments(self, rows: list[dict]) -> None:
        now = time.time()
        for r in rows:
            sym = r["symbol"]
            # TickFlow 返回键为 "ext"（dict）；也兼容已序列化的 "ext_json"
            ext = r.get("ext_json", r.get("ext"))
            if isinstance(ext, (dict, list)):
                ext = json.dumps(ext, ensure_ascii=False)
            self._conn.execute(
                "INSERT INTO instruments (symbol, exchange, code, name, type, region, ext_json,"
                " updated_at) VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, type=excluded.type,"
                " region=excluded.region, ext_json=excluded.ext_json,"
                " updated_at=excluded.updated_at",
                (sym, r.get("exchange") or sym.split(".")[-1], r.get("code") or sym.split(".")[0],
                 r.get("name"), r.get("type"), r.get("region"), ext, now))
        self._conn.commit()

    def get_instrument(self, symbol: str) -> dict | None:
        row = self._conn.execute(
            "SELECT symbol, exchange, code, name, type, region, ext_json"
            " FROM instruments WHERE symbol=?", (symbol,)).fetchone()
        if row is None:
            return None
        cols = ["symbol", "exchange", "code", "name", "type", "region", "ext_json"]
        return {c: row[i] for i, c in enumerate(cols)}

    def list_coverage(self, q: str | None = None, period: str | None = None,
                      page: int = 1, size: int = 50) -> tuple[int, list[dict]]:
        """分页列出已存 K 线覆盖索引（LEFT JOIN instruments 取 code/name）。

        q 匹配 symbol/code/name（LIKE）；period 精确过滤。返回 (total, rows)，
        row 形如 {symbol, code, name, period, start_ms, end_ms, updated_at}。
        """
        page, size = max(1, page), max(1, size)
        where, args = [], []
        if period:
            where.append("c.period = ?")
            args.append(period)
        if q:
            pat = f"%{q}%"
            where.append("(c.symbol LIKE ? OR i.code LIKE ? OR i.name LIKE ?)")
            args += [pat, pat, pat]
        cond = f"WHERE {' AND '.join(where)}" if where else ""
        base = (f"FROM kline_coverage c LEFT JOIN instruments i ON i.symbol = c.symbol {cond}")
        total = self._conn.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
        rows = self._conn.execute(
            f"SELECT c.symbol, i.code, i.name, c.period, c.start_ms, c.end_ms, c.updated_at {base}"
            f" ORDER BY c.symbol ASC, c.period ASC LIMIT ? OFFSET ?",
            (*args, size, (page - 1) * size)).fetchall()
        return total, [
            {"symbol": r[0], "code": r[1], "name": r[2], "period": r[3],
             "start_ms": r[4], "end_ms": r[5], "updated_at": r[6]} for r in rows]

    def add_universe_members(self, universe_id: str, symbols: list[str]) -> None:
        now = time.time()
        self._conn.executemany(
            "INSERT OR IGNORE INTO universe_members (universe_id, symbol, added_at)"
            " VALUES (?,?,?)", [(universe_id, s, now) for s in symbols])
        self._conn.commit()

    def get_universe_symbols(self, universe_id: str) -> list[str]:
        return [r[0] for r in self._conn.execute(
            "SELECT symbol FROM universe_members WHERE universe_id=? ORDER BY symbol",
            (universe_id,))]

    # ---- ex factors ----
    def upsert_ex_factors(self, symbol: str, factors: list[tuple[int, float]]) -> None:
        self._conn.executemany(
            "INSERT OR IGNORE INTO ex_factors (symbol, ts_ms, ex_factor) VALUES (?,?,?)",
            [(symbol, ts, f) for ts, f in factors])
        self._conn.commit()

    def get_ex_factors(self, symbol: str) -> list[tuple[int, float]]:
        return [(r[0], r[1]) for r in self._conn.execute(
            "SELECT ts_ms, ex_factor FROM ex_factors WHERE symbol=? ORDER BY ts_ms", (symbol,))]

    # ---- meta kv 通用标记（除权因子同步标记、日历版本等） ----
    def get_meta_flag(self, key: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM meta_kv WHERE key=?", (key,)).fetchone() is not None

    def set_meta_flag(self, key: str) -> None:
        self._conn.execute(
            "INSERT INTO meta_kv (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(time.time())))
        self._conn.commit()

    def get_meta_ts(self, key: str) -> float | None:
        """meta_kv 存的是 set_meta_flag 写入的时间戳；返回 float 或 None。"""
        row = self._conn.execute("SELECT value FROM meta_kv WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        try:
            return float(row[0])
        except (TypeError, ValueError):
            return None

    # ---- job reports ----
    def save_job_report(self, job: str, report: dict) -> None:
        self._conn.execute(
            "INSERT INTO job_reports (job, report_json, created_at) VALUES (?,?,?)",
            (job, json.dumps(report, ensure_ascii=False), time.time()))
        self._conn.commit()
