# tests/test_monitor_daemon.py
import pandas as pd
from monitor.daemon import MonitorDaemon, edge_transition, in_trading_hours
from monitor.store import MonitorStore


def test_edge_transition():
    assert edge_transition(0, True) == "on"
    assert edge_transition(1, False) == "off"
    assert edge_transition(1, True) is None
    assert edge_transition(0, False) is None
    assert edge_transition(1, None) is None


def test_in_trading_hours():
    import datetime as dt
    def ms(h, m):  # 北京时间
        return int(dt.datetime(2026, 9, 7, h, m).timestamp() * 1000)  # 周一
    assert in_trading_hours(ms(10, 0)) and in_trading_hours(ms(14, 30))
    assert not in_trading_hours(ms(12, 0)) and not in_trading_hours(ms(9, 0))


def _mk(tmp_path, script):
    st = MonitorStore(tmp_path / "m.db")
    tid = st.add_task("t1", "600869.SH", script, interval_sec=60, notify=1)
    day = pd.DataFrame({"timestamp": [1000], "open": [1.0], "high": [1.0],
                        "low": [1.0], "close": [11.0], "volume": [100],
                        "amount": [1100.0]})
    dc = type("DC", (), {"get_klines": lambda s, *a, **k: day})()
    fs = type("FS", (), {"get": lambda s, *a, **k: pd.Series([1.0], index=[1000])})()
    return st, tid, dc, fs


def test_tick_edge_notifies(tmp_path, monkeypatch):
    st, tid, dc, fs = _mk(tmp_path, 'def check(ctx):\n    return {"on": True, "msg": "go"}\n')
    sent = []
    d = MonitorDaemon(st, dc, fs, send_fn=sent.append)
    import datetime as dt
    now = int(dt.datetime(2026, 9, 7, 10, 0).timestamp() * 1000)
    monkeypatch.setattr("monitor.daemon.in_trading_hours", lambda ts: True)
    d.tick(now)
    t = st.get_task(tid)
    assert t["lamp_on"] == 1 and t["poll_count"] == 1
    assert len(st.list_signals(tid)) == 1 and len(sent) == 1 and "灯亮" in sent[0]
    d.tick(now + 61_000)   # 条件仍满足：不重复通知
    assert len(sent) == 1 and len(st.list_signals(tid)) == 1


def test_tick_disabled_and_interval(tmp_path, monkeypatch):
    st, tid, dc, fs = _mk(tmp_path, 'def check(ctx):\n    return {"on": True}\n')
    monkeypatch.setattr("monitor.daemon.in_trading_hours", lambda ts: True)
    import datetime as dt
    now = int(dt.datetime(2026, 9, 7, 10, 0).timestamp() * 1000)
    st.set_enabled(tid, 0)
    d = MonitorDaemon(st, dc, fs, send_fn=lambda t: None)
    d.tick(now)
    assert st.get_task(tid)["poll_count"] == 0     # disabled 跳过
    st.set_enabled(tid, 1)
    d.tick(now)
    assert st.get_task(tid)["poll_count"] == 1
    d.tick(now + 30_000)                            # interval 未到
    assert st.get_task(tid)["poll_count"] == 1


def test_tick_script_error_isolated(tmp_path, monkeypatch):
    st, tid, dc, fs = _mk(tmp_path, 'def check(ctx):\n    raise RuntimeError("boom")\n')
    monkeypatch.setattr("monitor.daemon.in_trading_hours", lambda ts: True)
    d = MonitorDaemon(st, dc, fs, send_fn=lambda t: None)
    d.tick()
    t = st.get_task(tid)
    assert t["error_count"] == 1 and "boom" in t["last_error"] and t["lamp_on"] == 0


def test_tick_send_fn_raises_signal_kept(tmp_path, monkeypatch):
    """推送异常不杀循环：信号照常写入，last_error 记 bark 推送失败。"""
    st, tid, dc, fs = _mk(tmp_path, 'def check(ctx):\n    return {"on": True, "msg": "go"}\n')
    monkeypatch.setattr("monitor.daemon.in_trading_hours", lambda ts: True)

    def boom_send(text):
        raise OSError("network down")

    d = MonitorDaemon(st, dc, fs, send_fn=boom_send)
    d.tick()  # 不抛异常
    t = st.get_task(tid)
    assert t["lamp_on"] == 1
    assert len(st.list_signals(tid)) == 1
    assert t["error_count"] == 1 and "bark 推送失败" in t["last_error"]


def test_tick_price_unexpected_error_signal_kept(tmp_path, monkeypatch):
    """边沿分支取价抛非 DataError：信号写入 price=None，灯已翻，循环存活。"""
    st, tid, dc, fs = _mk(tmp_path, 'def check(ctx):\n    return {"on": True}\n')
    monkeypatch.setattr("monitor.daemon.in_trading_hours", lambda ts: True)

    def get_klines(symbol, period, *a, **k):
        if period == "1m":
            raise RuntimeError("1m store corrupted")
        return dc.get_klines(symbol, period, *a, **k)

    dc2 = type("DC2", (), {"get_klines": staticmethod(get_klines)})()
    d = MonitorDaemon(st, dc2, fs, send_fn=lambda t: True)
    d.tick()  # 不抛异常
    t = st.get_task(tid)
    assert t["lamp_on"] == 1                       # 灯已翻
    sigs = st.list_signals(tid)
    assert len(sigs) == 1 and sigs[0]["price"] is None
