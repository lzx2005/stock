# tests/test_monitor_runtime.py
import pandas as pd
import pytest
from monitor.runtime import MonitorContext, load_check, run_check, DataError


class FakeDC:
    def __init__(self):
        day = pd.DataFrame({"timestamp": [1000, 2000], "open": [1, 2],
                            "high": [1, 2], "low": [1, 2], "close": [10.0, 11.0],
                            "volume": [100, 200], "amount": [1000.0, 2200.0]})
        self.min = day.copy(); self.day = day
    def get_klines(self, symbol, period, s, e, adjust="forward"):
        return self.min if period == "1m" else self.day


class FakeFS:
    def get(self, symbol, name, params, period, s, e):
        return pd.Series([1.0, 2.0], index=[1000, 2000])


def ctx():
    return MonitorContext(FakeDC(), FakeFS(), "600869.SH")


def test_ctx_methods():
    c = ctx()
    assert c.price() == 11.0
    assert len(c.minute_bars()) == 2 and len(c.daily(5)) == 2
    assert c.factor("ma", {"n": 20}, 60).iloc[-1] == 2.0


def test_price_empty_raises():
    c = ctx(); c.dc.min = c.dc.min.iloc[0:0]
    with pytest.raises(DataError):
        c.price()


def test_load_and_run_check():
    script = 'def check(ctx):\n    return {"on": True, "msg": "hi"}\n'
    fn = load_check(script)
    assert callable(fn)
    out = run_check(script, ctx())
    assert out == {"on": True, "msg": "hi"}


def test_load_check_missing():
    with pytest.raises(ValueError):
        load_check("x = 1")


def test_run_check_bad_return():
    with pytest.raises(ValueError):
        run_check('def check(ctx):\n    return {"on": "yes"}\n', ctx())
