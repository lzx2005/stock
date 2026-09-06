import time

import pandas as pd
import pytest

from scripts.validate_watch import compile_check, replay_daily


def _fake_dc(df):
    return type("DC", (), {"get_klines": lambda s, sym, p, a, b, adjust="forward":
                           df[df.timestamp <= b] if p == "1d" else df.iloc[0:0]})()


def _fake_fs():
    return type("FS", (), {"get": lambda s, *a, **k: pd.Series(dtype=float)})()


def test_replay_daily_counts_triggers():
    ts = [i * 86_400_000 for i in range(5)]
    df = pd.DataFrame({"timestamp": ts, "open": [1]*5, "high": [1]*5,
                       "low": [1]*5, "close": [9, 11, 9, 11, 11],
                       "volume": [1]*5, "amount": [1.0]*5})
    dc = _fake_dc(df)
    fs = _fake_fs()
    script = 'def check(ctx):\n    return {"on": ctx.daily(5)["close"].iloc[-1] > 10}\n'
    hits = replay_daily(script, "X.SH", dc, fs, days=5)
    assert len(hits) == 3


def test_replay_daily_price_fallback_local_midnight_bars():
    """回归：日K 时间戳=本地 00:00 时，依赖 ctx.price() 的脚本回放也必须触发。"""
    ts = [int(time.mktime((2026, 8, 25 + i, 0, 0, 0, 0, 0, -1)) * 1000)
          for i in range(5)]
    df = pd.DataFrame({"timestamp": ts, "open": [1]*5, "high": [1]*5,
                       "low": [1]*5, "close": [9, 11, 9, 11, 11],
                       "volume": [1]*5, "amount": [1.0]*5})
    dc = _fake_dc(df)  # 1m 恒空 → price() 必须走回放日线兜底
    fs = _fake_fs()
    script = 'def check(ctx):\n    return {"on": ctx.price() > 10}\n'
    hits = replay_daily(script, "X.SH", dc, fs, days=5)
    assert len(hits) == 3


def test_replay_daily_empty_data_returns_empty():
    df = pd.DataFrame({"timestamp": [], "open": [], "high": [], "low": [],
                       "close": [], "volume": [], "amount": []})
    script = 'def check(ctx):\n    return {"on": True}\n'
    assert replay_daily(script, "X.SH", _fake_dc(df), _fake_fs(), days=5) == []


def test_replay_daily_dataerror_days_skipped():
    ts = [int(time.mktime((2026, 8, 25 + i, 0, 0, 0, 0, 0, -1)) * 1000)
          for i in range(3)]
    df = pd.DataFrame({"timestamp": ts, "open": [1]*3, "high": [1]*3,
                       "low": [1]*3, "close": [11]*3,
                       "volume": [1]*3, "amount": [1.0]*3})
    script = ('from monitor.runtime import DataError\n'
              'def check(ctx):\n    raise DataError("当日无数据")\n')
    hits = replay_daily(script, "X.SH", _fake_dc(df), _fake_fs(), days=5)
    assert hits == []


def test_compile_check_ok():
    compile_check('def check(ctx):\n    return {"on": True}\n')


def test_compile_check_syntax_error():
    with pytest.raises(SyntaxError):
        compile_check("def check(ctx:\n")
