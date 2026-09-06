"""盯盘脚本契约：MonitorContext（脚本取数接口）+ 脚本加载/校验。

盯盘脚本约定：定义 `def check(ctx) -> dict`，返回
{"on": True/False/None, "msg": str}——一盏信号灯：条件成立灯亮，不成立灯灭，
None 表示本轮不判断（灯状态不变）。
"""

import time
from typing import Callable

import numpy as np

import factors.factors  # noqa: F401  显式注册因子，脚本内 factor() 可用

_DAY_MS = 86_400_000


class DataError(Exception):
    """无当日数据（未开盘/停牌/数据缺失）。"""


class MonitorContext:
    """盯盘脚本的取数上下文。

    asof_ms 为 None 时窗口截止到当前时间；设置后所有数据窗口截止 asof_ms
    （Task 8 回放用）。
    """

    def __init__(self, dc, fs, symbol: str, asof_ms: int | None = None):
        self.dc = dc
        self.fs = fs
        self.symbol = symbol
        self._replay = asof_ms is not None  # 显式 asof = 回放模式
        self.asof_ms = asof_ms if asof_ms is not None else int(time.time() * 1000)

    def _today_start_ms(self) -> int:
        t = time.localtime(self.asof_ms / 1000)
        return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000)

    def minute_bars(self):
        """当日分钟 K（今日 0 点 ~ asof）；空 df 原样返回。"""
        return self.dc.get_klines(
            self.symbol, "1m", self._today_start_ms(), self.asof_ms, adjust="forward"
        )

    def price(self) -> float:
        """最新价 = minute_bars() 最后一根 close。

        回放模式（显式 asof_ms）且当日无分钟数据时，兜底取当日日K 收盘
        （分钟缓存仅 1 年深度，日线口径回放需全时段可用）；
        live 模式无当日数据抛 DataError。
        """
        df = self.minute_bars()
        if df is not None and len(df) > 0:
            return float(df["close"].iloc[-1])
        if self._replay:
            d = self.daily(1)
            if d is not None and len(d) > 0:
                return float(d["close"].iloc[-1])
        raise DataError(f"{self.symbol} 无当日分钟数据")

    def daily(self, n: int):
        """最近 n 根日 K（含今日合成日K）。start 取今日 -2n 自然日后 tail(n)。"""
        start = self._today_start_ms() - 2 * n * _DAY_MS
        df = self.dc.get_klines(self.symbol, "1d", start, self.asof_ms, adjust="forward")
        return df.tail(n)

    def factor(self, name: str, params: dict, n: int):
        """日线因子序列，窗口同 daily(n)。"""
        start = self._today_start_ms() - 2 * n * _DAY_MS
        return self.fs.get(self.symbol, name, params, "1d", start, self.asof_ms)


def _norm_flag(v):
    """numpy 布尔（pandas 比较的产物）归一为 Python bool，其余原样返回。"""
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def load_check(script: str) -> Callable:
    """exec 脚本取 check 函数；无 check 或不可调用 → ValueError。"""
    ns: dict = {}
    exec(script, ns)  # noqa: S102  盯盘脚本为本机用户自写，属预期用法
    fn = ns.get("check")
    if not callable(fn):
        raise ValueError("脚本必须定义可调用的 check(ctx) 函数")
    return fn


def run_check(script: str, ctx) -> dict:
    """执行 check 并校验返回值。

    合法返回：dict 且 on ∈ {True, False, None}；缺省补 None，msg 转 str。
    非法 → ValueError。
    """
    out = load_check(script)(ctx)
    if not isinstance(out, dict):
        raise ValueError(f"check 必须返回 dict，实际 {type(out).__name__}")
    on = _norm_flag(out.get("on"))
    if on is not True and on is not False and on is not None:
        raise ValueError(f"on 必须为 True/False/None，实际 {on!r}")
    msg = out.get("msg")
    return {"on": on, "msg": None if msg is None else str(msg)}
