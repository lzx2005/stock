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


class FakeKlines:
    """模拟 tf.klines：按调用顺序返回预设结果或抛异常。"""
    def __init__(self):
        self.calls = []
        self.script = []        # get() 队列: DataFrame | Exception
        self.batch_calls = []
        self.batch_script = []  # batch() 队列: dict[symbol, DataFrame] | Exception

    def queue(self, item):
        self.script.append(item)

    def get(self, symbol, period="1d", count=None, start_time=None, end_time=None,
            adjust=None, as_dataframe=False):
        self.calls.append(dict(symbol=symbol, period=period, count=count,
                               start_time=start_time, end_time=end_time, adjust=adjust))
        item = self.script.pop(0) if self.script else pd.DataFrame()
        if isinstance(item, Exception):
            raise item
        return item

    def batch(self, symbols, period="1d", count=None, start_time=None, end_time=None,
              adjust=None, as_dataframe=False):
        self.batch_calls.append(dict(symbols=list(symbols), period=period, count=count,
                                     start_time=start_time, end_time=end_time, adjust=adjust))
        item = self.batch_script.pop(0) if self.batch_script else {}
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
