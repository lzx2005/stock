import pandas as pd
import pytest

from datacenter import DataCenter
from datacenter.jobs.daily_maintenance import run_daily_maintenance
from tests.conftest import FakeTickFlow, make_kline_df

T0, DAY = 1754011800000, 86_400_000


def test_daily_maintenance_appends_and_updates(tmp_path):
    fake = FakeTickFlow(symbols=["a.SH", "b.SH"])
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    dc.list_symbols()
    # 预置历史覆盖：截至昨日
    dc.meta.extend_coverage("a.SH", "1d", T0, T0 + 5 * DAY)
    dc.meta.extend_coverage("b.SH", "1d", T0, T0 + 5 * DAY)
    # 今日数据（intraday/kline 接口回今日日K）。
    # 反向分页下，窗口 [昨日+1, 今日] 取到今日 bar 后（min_ts=今日 > start）还会向旧探测一页，
    # 该页对真实服务端返回空；fake 需按此建模，否则探测页会误吞下一标的的队列项。
    fake.klines.queue(make_kline_df("a.SH", T0 + 6 * DAY, 1, DAY))
    fake.klines.queue(pd.DataFrame())  # a.SH 探测页 → 空终止
    fake.klines.queue(make_kline_df("b.SH", T0 + 6 * DAY, 1, DAY))
    fake.klines.queue(pd.DataFrame())  # b.SH 探测页 → 空终止
    report = run_daily_maintenance(dc, today_ms=T0 + 6 * DAY)
    assert report["symbols_updated"] == 2
    assert report["ex_factors_checked"] == 2
    df = dc.get_klines("a.SH", "1d", T0 + 6 * DAY, T0 + 7 * DAY, adjust="none")
    assert len(df) == 1  # 当日已固化


def test_daily_maintenance_idempotent(tmp_path):
    """连跑两次当日不产生重复数据（DoD #4）。"""
    fake = FakeTickFlow(symbols=["a.SH"])
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    dc.list_symbols()
    dc.meta.extend_coverage("a.SH", "1d", T0, T0 + 5 * DAY)
    fake.klines.queue(make_kline_df("a.SH", T0 + 6 * DAY, 1, DAY))
    run_daily_maintenance(dc, today_ms=T0 + 6 * DAY)
    run_daily_maintenance(dc, today_ms=T0 + 6 * DAY)  # 幂等：不再拉取
    df = dc.klines.read(["a.SH"], "1d", T0 + 6 * DAY, T0 + 6 * DAY)
    assert len(df) == 1  # 不重复


def test_daily_maintenance_saves_report(tmp_path):
    fake = FakeTickFlow(symbols=["a.SH"])
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    dc.list_symbols()
    report = run_daily_maintenance(dc, today_ms=T0 + 6 * DAY)
    row = dc.meta._conn.execute(
        "SELECT job, report_json FROM job_reports ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None and row[0] == "daily"
    assert '"symbols_updated"' in row[1]


def test_daily_solidifies_minute_klines(tmp_path):
    """日终把当日各分钟周期从 REST 拉下写入 klines/，coverage 扩展到今日。"""
    fake = FakeTickFlow(symbols=["a.SH"])
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    dc.list_symbols()
    dc.meta.extend_coverage("a.SH", "1m", T0 - 30 * DAY, T0 - 1)  # 历史已覆盖到昨日
    fake.klines.queue(make_kline_df("a.SH", T0, 10, 60_000))      # 当日 10 根 1m
    report = run_daily_maintenance(dc, today_ms=T0 + 5 * 3600_000, periods=["1m"])
    assert report["symbols_updated"] >= 1
    df = dc.klines.read(["a.SH"], "1m", T0, T0 + 5 * 3600_000)
    assert len(df) == 10
    assert dc.meta.get_coverage("a.SH", "1m")[1] >= T0 + 5 * 3600_000


def test_ws_rest_reconciliation(tmp_path):
    """realtime/ 有当日快照时，日终把 WS 聚合的 1m 与 REST 1m 比对，差异写入报告。"""
    fake = FakeTickFlow(symbols=["a.SH"])
    dc = DataCenter(data_dir=tmp_path / "data", client_tf=fake)
    dc.list_symbols()
    # REST 当日 2 根 1m：close=10.5, volume=1000/根（make_kline_df: base=10）
    fake.klines.queue(make_kline_df("a.SH", T0, 2, 60_000))
    # WS 快照：第 1 根 1m 窗口 vol 差分=1000 与 REST 一致；第 2 根差分=500 vs REST 1000
    snaps = pd.DataFrame([
        {"symbol": "a.SH", "ts_ms": T0 + 1000, "last_price": 10.0, "volume": 500, "turnover": 5000.0, "kind": "snapshot"},
        {"symbol": "a.SH", "ts_ms": T0 + 59_000, "last_price": 10.5, "volume": 1000, "turnover": 10000.0, "kind": "snapshot"},
        {"symbol": "a.SH", "ts_ms": T0 + 61_000, "last_price": 10.5, "volume": 1100, "turnover": 11000.0, "kind": "snapshot"},
        {"symbol": "a.SH", "ts_ms": T0 + 119_000, "last_price": 10.5, "volume": 1500, "turnover": 15000.0, "kind": "snapshot"},
    ])
    dc.realtime.write(snaps)
    report = run_daily_maintenance(dc, today_ms=T0 + 5 * 3600_000, periods=["1m"])
    assert report["reconcile_mismatches"]  # 第 2 根 volume 差异 >1% 被报出
