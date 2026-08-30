import pandas as pd
import pytest


def make_kline_df(symbol: str, start_ms: int, n: int, step_ms: int) -> pd.DataFrame:
    """确定性合成 K 线：价格由 start_ms 决定，便于断言。"""
    ts = [start_ms + i * step_ms for i in range(n)]
    base = (start_ms // 1000) % 100 + 10.0
    return pd.DataFrame({
        "symbol": symbol,
        "timestamp": ts,
        "open": [base] * n,
        "high": [base + 1] * n,
        "low": [base - 1] * n,
        "close": [base + 0.5] * n,
        "volume": [1000] * n,
        "amount": [base * 1000] * n,
    })


class Repeat:
    """脚本项包装：永久重复返回（模拟忽略 start_time、持续返回同一满页的异常服务端）。"""
    def __init__(self, item):
        self.item = item


class FakeKlines:
    """模拟 tf.klines：按调用顺序返回预设结果或抛异常。
    fuse_after：超过该调用次数抛 RuntimeError——死循环防护测试的保险丝，
    让"未加固"的代码快速失败而不是挂起到 pytest-timeout。"""
    def __init__(self, fuse_after=None):
        self.calls = []
        self.script = []        # get() 队列: DataFrame | Exception | Repeat
        self.batch_calls = []
        self.batch_script = []  # batch() 队列: dict[symbol, DataFrame] | Exception | Repeat
        self.fuse_after = fuse_after

    def queue(self, item):
        self.script.append(item)

    def queue_forever(self, item):
        self.script.append(Repeat(item))

    def batch_queue_forever(self, item):
        self.batch_script.append(Repeat(item))

    def _fuse(self, n):
        if self.fuse_after is not None and n > self.fuse_after:
            raise RuntimeError(f"fake fuse blown after {self.fuse_after} calls")

    @staticmethod
    def _next(script, default):
        if not script:
            return default
        head = script[0]
        return head.item if isinstance(head, Repeat) else script.pop(0)

    def get(self, symbol, period="1d", count=None, start_time=None, end_time=None,
            adjust=None, as_dataframe=False):
        self.calls.append(dict(symbol=symbol, period=period, count=count,
                               start_time=start_time, end_time=end_time, adjust=adjust))
        self._fuse(len(self.calls))
        item = self._next(self.script, pd.DataFrame())
        if isinstance(item, Exception):
            raise item
        return item

    def batch(self, symbols, period="1d", count=None, start_time=None, end_time=None,
              adjust=None, as_dataframe=False):
        self.batch_calls.append(dict(symbols=list(symbols), period=period, count=count,
                                     start_time=start_time, end_time=end_time, adjust=adjust))
        self._fuse(len(self.batch_calls))
        item = self._next(self.batch_script, {})
        if isinstance(item, Exception):
            raise item
        return item


class FakeUniverses:
    def __init__(self, symbols):
        self._symbols = symbols
    def get(self, universe_id):
        return {"id": universe_id, "symbols": self._symbols}


class FakeTickFlow:
    def __init__(self, symbols=None):
        self.klines = FakeKlines()
        self.universes = FakeUniverses(symbols or [])


@pytest.fixture
def fake_tf():
    return FakeTickFlow(symbols=["600000.SH", "000001.SZ"])


@pytest.fixture
def tmp_data_dir(tmp_path):
    return tmp_path / "data"
