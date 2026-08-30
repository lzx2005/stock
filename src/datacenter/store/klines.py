"""K线 Parquet 存储（KlineStore）。

设计约定：
- 分区规则：分钟周期（MINUTE_PERIODS）`period={p}/year={yyyy}/month={mm}/`，
  日线及以上 `period={p}/year={yyyy}/`；year/month 按 **Asia/Shanghai** 时区
  从 timestamp（int64 毫秒）推导。
- 文件名 `part-{yyyymmddHHMMSSffffff}-{tag}.parquet`：时间戳在文件名最前，
  保证字典序 == 写入序（后续读取去重"后写胜出"依赖这一点）。
- 写入三步：写 `.tmp-` 临时文件 → `os.replace` 同目录原子 rename →
  调用方更新 coverage（本类不管 coverage）。
"""

import os
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from datacenter.client.tickflow_client import KLINE_COLUMNS, empty_klines
from datacenter.constants import ALL_PERIODS, MINUTE_PERIODS


class KlineStore:
    """K线 Parquet 存储。写入：按分区拆帧 → 写临时文件 → 原子 rename。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def write(self, df: pd.DataFrame, period: str, tag: str) -> list[Path]:
        if df is None or df.empty:
            return []
        df = df.copy()
        ts = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")
        df["year"] = ts.dt.strftime("%Y")
        partition_cols = ["year"]
        if period in MINUTE_PERIODS:
            df["month"] = ts.dt.strftime("%m")
            partition_cols.append("month")

        written = []
        for keys, part in df.groupby(partition_cols, observed=True):
            keys = keys if isinstance(keys, tuple) else (keys,)
            dirpath = self.root / f"period={period}" / f"year={keys[0]}"
            if len(keys) > 1:
                dirpath = dirpath / f"month={keys[1]}"
            dirpath.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            tmp = dirpath / f".tmp-{stamp}-{tag}.parquet"
            final = dirpath / f"part-{stamp}-{tag}.parquet"
            part.drop(columns=partition_cols).to_parquet(tmp, index=False, compression="zstd")
            os.replace(tmp, final)  # 同目录原子 rename
            written.append(final)
        return written

    def read(self, symbols: list[str], period: str,
             start_ms: int, end_ms: int) -> pd.DataFrame:
        """读取 K 线：分区裁剪 + 范围/标的过滤 + 去重（后写胜出）。

        去重依赖 read_parquet 的 filename 列按字典序 DESC——文件名
        `part-{写入时间戳}-{tag}.parquet` 时间戳前置，后写字典序更大。
        """
        if period not in ALL_PERIODS:
            raise ValueError(f"unknown period: {period}")
        if not symbols:
            return empty_klines()
        glob = str(self.root / f"period={period}" / "**" / "*.parquet")
        sql = """
            SELECT symbol, timestamp, open, high, low, close, volume, amount
            FROM read_parquet(?, hive_partitioning=true, filename=true, union_by_name=true)
            WHERE symbol = ANY(?::VARCHAR[]) AND timestamp BETWEEN ? AND ?
            QUALIFY row_number() OVER (
                PARTITION BY symbol, timestamp ORDER BY filename DESC
            ) = 1
            ORDER BY symbol, timestamp
        """
        try:
            out = duckdb.sql(sql, params=[glob, list(symbols), start_ms, end_ms]).df()
        except duckdb.IOException:
            return empty_klines()  # 尚无该周期数据
        return out[KLINE_COLUMNS]
