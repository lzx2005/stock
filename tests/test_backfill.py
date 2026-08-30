import pandas as pd
import pytest

from datacenter import DataCenter
from datacenter.jobs.backfill import backfill
from tests.conftest import FakeTickFlow, make_kline_df

T0, DAY = 1754011800000, 86_400_000


def make_dc(tmp_path, fake):
    # max_retries=0：失败测试依赖"异常立即抛出"，默认重试会消耗后续队列元素
    return DataCenter(data_dir=tmp_path / "data", client_tf=fake, rate_per_sec=10_000,
                      max_retries=0)


def test_backfill_fetches_all_pending_symbols(tmp_path):
    fake = FakeTickFlow(symbols=["a.SH", "b.SH", "c.SH"])
    fake.klines.batch_script = [
        {s: make_kline_df(s, T0, 3, DAY) for s in ["a.SH", "b.SH"]},
        {"c.SH": make_kline_df("c.SH", T0, 3, DAY)},
    ]
    dc = make_dc(tmp_path, fake)
    report = backfill(dc, periods=["1d"], start_ms=T0, end_ms=T0 + 3 * DAY,
                      batch_size=2)
    assert sorted(report["done"]) == ["a.SH", "b.SH", "c.SH"]
    assert report["failed"] == {}
    assert dc.meta.pending_symbols(["a.SH", "b.SH", "c.SH"], "1d") == []
    df = dc.get_klines("a.SH", "1d", T0, T0 + 3 * DAY)  # 缓存命中不回源
    assert len(df) == 3


def test_backfill_resume_skips_done(tmp_path):
    fake = FakeTickFlow(symbols=["a.SH", "b.SH"])
    dc = make_dc(tmp_path, fake)
    dc.list_symbols()
    dc.meta.mark_done("a.SH", "1d")  # 模拟上次已完成
    fake.klines.batch_script = [{"b.SH": make_kline_df("b.SH", T0, 3, DAY)}]
    report = backfill(dc, periods=["1d"], start_ms=T0, end_ms=T0 + 3 * DAY)
    assert report["done"] == ["b.SH"]
    assert fake.klines.batch_calls[0]["symbols"] == ["b.SH"]


def test_backfill_batch_failure_marks_whole_batch(tmp_path):
    fake = FakeTickFlow(symbols=["a.SH", "b.SH"])
    fake.klines.batch_script = [Exception("boom")]
    dc = make_dc(tmp_path, fake)
    report = backfill(dc, periods=["1d"], start_ms=T0, end_ms=T0 + 3 * DAY)
    assert report["done"] == []
    assert set(report["failed"]) == {"a.SH", "b.SH"}
    assert dc.meta.pending_symbols(["a.SH", "b.SH"], "1d") == ["a.SH", "b.SH"]


def test_backfill_empty_batch_result_still_marks_done(tmp_path):
    """批量返回空（如全部未上市期间）也必须标记 done + coverage，防止反复打空。"""
    fake = FakeTickFlow(symbols=["a.SH"])
    fake.klines.batch_script = [{}]
    dc = make_dc(tmp_path, fake)
    report = backfill(dc, periods=["1d"], start_ms=T0, end_ms=T0 + 3 * DAY)
    assert report["done"] == ["a.SH"]
    assert dc.meta.get_coverage("a.SH", "1d") == (T0, T0 + 3 * DAY)
