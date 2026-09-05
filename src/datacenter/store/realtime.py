"""实时行情 Parquet 存储（RealtimeStore）。

与 KlineStore 同模式：临时文件 → 原子 rename → DuckDB 读。
- 分区：`date=YYYY-MM-DD`（**Asia/Shanghai** 时区）
- 文件：`rt-{yyyymmddHHMMSSffffff}.parquet`（时间戳前置，字典序 == 写入序，读取去重后写胜出）
- 列：`symbol, ts_ms, last_price, volume, turnover, kind`（kind: snapshot/tick）
- 独立于 `data/klines/` 与 kline_coverage 体系；本类不管 coverage
"""

import os
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from datacenter.store._duck import query_df

REALTIME_COLUMNS = ["symbol", "ts_ms", "last_price", "volume", "turnover", "kind"]


def empty_realtime() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in {
        "symbol": "object", "ts_ms": "int64", "last_price": "float64",
        "volume": "int64", "turnover": "float64", "kind": "object",
    }.items()})


class RealtimeStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def write(self, df: pd.DataFrame) -> list[Path]:
        """按 date 分区写盘，返回写入的文件路径列表（空 df 返回 []）。"""
        if df is None or df.empty:
            return []
        df = df.copy()
        ts = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")
        df["date"] = ts.dt.strftime("%Y-%m-%d")

        written = []
        for date, part in df.groupby("date", observed=True):
            dirpath = self.root / f"date={date}"
            dirpath.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            tmp = dirpath / f".tmp-rt-{stamp}.parquet"
            final = dirpath / f"rt-{stamp}.parquet"
            try:
                part.drop(columns=["date"]).to_parquet(tmp, index=False, compression="zstd")
                os.replace(tmp, final)
            finally:
                tmp.unlink(missing_ok=True)  # 不残留 .tmp（会被读取端 glob 命中）
            written.append(final)
        return written

    def read(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        """读某标的 [start_ms, end_ms] 的实时快照，按 (symbol, ts_ms) 后写去重。"""
        glob = str(self.root / "**" / "*.parquet")
        sql = """
            SELECT symbol, ts_ms, last_price, volume, turnover, kind
            FROM read_parquet(?, hive_partitioning=true, filename=true, union_by_name=true)
            WHERE symbol = ? AND ts_ms BETWEEN ? AND ?
              AND filename NOT LIKE '%/.tmp-%'
            QUALIFY row_number() OVER (
                PARTITION BY symbol, ts_ms ORDER BY filename DESC
            ) = 1
            ORDER BY ts_ms
        """
        try:
            out = query_df(sql, [glob, symbol, start_ms, end_ms])
        except duckdb.IOException:
            return empty_realtime()  # 尚无实时数据
        for col in REALTIME_COLUMNS:
            if col not in out.columns:
                out[col] = pd.NA
        return out[REALTIME_COLUMNS].reset_index(drop=True)
