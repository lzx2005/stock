"""财务数据 SQLite 存储。

表结构由数据驱动：pandas to_sql 动态建表，字段变更不用改代码。
缓存键 (symbol, period_end)；fin_fetch_log 控制 latest 刷新（TTL 24h）。
"""

import sqlite3
import time
from pathlib import Path

import pandas as pd

TABLES = {"income": "fin_income", "balance_sheet": "fin_balance",
          "cash_flow": "fin_cashflow", "metrics": "fin_metrics", "shares": "fin_shares"}
LATEST_TTL_SEC = 24 * 3600


class FinancialStore:
    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS fin_fetch_log ("
                           "symbol TEXT, tbl TEXT, fetched_at REAL, PRIMARY KEY (symbol, tbl))")
        self._conn.commit()

    def _fetched_at(self, symbol: str, table: str) -> float | None:
        row = self._conn.execute("SELECT fetched_at FROM fin_fetch_log WHERE symbol=? AND tbl=?",
                                 (symbol, table)).fetchone()
        return row[0] if row else None

    def needs_fetch(self, symbol: str, table: str, latest: bool) -> bool:
        ts = self._fetched_at(symbol, table)
        if ts is None:
            return True
        return latest and (time.time() - ts) > LATEST_TTL_SEC

    def save(self, table: str, df: pd.DataFrame) -> None:
        """DELETE 该 (symbol, period_end) 旧行 + 追加新行，包在事务里防半截。
        注意：pandas to_sql 对 sqlite3 连接会自行 commit，故先 BEGIN IMMEDIATE，
        to_sql 的 commit 落盘后显式补记 fin_fetch_log；失败时 ROLLBACK。"""
        if df is None or df.empty:
            return
        tbl = TABLES[table]
        exists = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tbl,)).fetchone()
        if exists is None:
            # 首次保存：用 df 空骨架动态建表（表结构由数据驱动，不手写 DDL）
            df.iloc[0:0].to_sql(tbl, self._conn, if_exists="replace", index=False)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            keys = df[["symbol", "period_end"]].drop_duplicates()
            for _, r in keys.iterrows():
                self._conn.execute(f"DELETE FROM {tbl} WHERE symbol=? AND period_end=?",
                                   (r["symbol"], r["period_end"]))
            df.to_sql(tbl, self._conn, if_exists="append", index=False)
            now = time.time()
            self._conn.executemany(
                "INSERT INTO fin_fetch_log VALUES (?,?,?) ON CONFLICT(symbol, tbl)"
                " DO UPDATE SET fetched_at=excluded.fetched_at",
                [(s, table, now) for s in df["symbol"].unique()])
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def load(self, table: str, symbols: list[str], latest: bool) -> pd.DataFrame:
        tbl = TABLES[table]
        marks = ",".join("?" * len(symbols))
        try:
            df = pd.read_sql(f"SELECT * FROM {tbl} WHERE symbol IN ({marks})",
                             self._conn, params=symbols)
        except pd.errors.DatabaseError:
            return pd.DataFrame()
        if latest and not df.empty:
            df = df.sort_values("period_end").groupby("symbol", as_index=False).tail(1)
        return df

    def close(self):
        self._conn.close()
