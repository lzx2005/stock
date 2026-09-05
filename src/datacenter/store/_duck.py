"""DuckDB 只读查询小助手。

`duckdb.sql()` 复用进程级默认连接，**线程不安全**——并发查询会抛
InvalidInputException（甚至死锁）。webui 点击下钻并发两个 klines 请求即踩中
（复现：20/20 并发对必有 1 个 500）。这里每次查询用独立连接，天然线程安全；
本地文件只读、毫秒级，连接创建开销可忽略。
"""

import duckdb
import pandas as pd


def query_df(sql: str, params: list) -> pd.DataFrame:
    """在新连接上执行只读 SQL，返回 DataFrame（连接用完即关）。"""
    con = duckdb.connect()
    try:
        return con.execute(sql, params).df()
    finally:
        con.close()


def query_scalar(sql: str, params: list):
    """在新连接上执行只读 SQL，返回首行首列（连接用完即关）。"""
    con = duckdb.connect()
    try:
        row = con.execute(sql, params).fetchone()
        return row[0] if row is not None else None
    finally:
        con.close()
