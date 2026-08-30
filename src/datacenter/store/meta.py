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
"""


class MetaStore:
    """SQLite 元数据：K线覆盖区间、回填进度、标的清单。WAL 模式支持多读单写。"""

    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)

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
