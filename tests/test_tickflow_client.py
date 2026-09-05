import logging

import pandas as pd
import pytest

from datacenter.client.tickflow_client import TickFlowClient, classify_error
from datacenter.exceptions import RateLimitError, TickFlowError
from tests.conftest import make_kline_df


def make_client(fake_tf, **kw):
    return TickFlowClient(tf=fake_tf, rate_per_sec=1000, max_retries=2,
                          sleep=lambda s: None, **kw)


def test_retry_on_rate_limit_then_success(fake_tf):
    df = make_kline_df("600000.SH", 1000, 3, 1000)
    fake_tf.klines.queue(Exception("429 too many requests"))
    fake_tf.klines.queue(df)
    client = make_client(fake_tf)
    out = client.get_klines_range("600000.SH", "1d", 1000, 4000)
    assert len(out) == 3
    assert len(fake_tf.klines.calls) == 2  # 重试了一次


def test_rate_limit_exhausted_raises(fake_tf):
    for _ in range(3):
        fake_tf.klines.queue(Exception("rate limit exceeded"))
    client = make_client(fake_tf)
    with pytest.raises(RateLimitError):
        client.get_klines_range("600000.SH", "1d", 1000, 4000)


def test_client_error_not_retried(fake_tf):
    fake_tf.klines.queue(Exception("INVALID_PERIOD: 2d"))
    client = make_client(fake_tf)
    with pytest.raises(TickFlowError) as exc_info:
        client.get_klines_range("600000.SH", "1d", 1000, 4000)
    assert not isinstance(exc_info.value, RateLimitError)
    assert len(fake_tf.klines.calls) == 1  # 不重试


def test_pagination_accumulates_until_start(fake_tf):
    # 反向分页：第一页满 5000 -> 向旧翻；第二页触及请求起点(min_ts==start_ms) -> 停止
    page1 = make_kline_df("600000.SH", 5000 * 60_000, 5000, 60_000)   # 最近 5000 根
    page2 = make_kline_df("600000.SH", 0, 50, 60_000)                 # 更早 50 根，min_ts=0
    fake_tf.klines.queue(page1)
    fake_tf.klines.queue(page2)
    client = make_client(fake_tf)
    out = client.get_klines_range("600000.SH", "1m", 0, 10**13)
    assert len(out) == 5050
    assert len(fake_tf.klines.calls) == 2
    # 第二页的 end_time 接续第一页最旧时间戳（反向）
    assert fake_tf.klines.calls[1]["end_time"] == page1["timestamp"].min() - 1


def test_pagination_short_page_continues_backward(fake_tf):
    # 服务端每页上限可能略低于 MAX_PAGE：页长未满但仍应继续向旧翻
    page1 = make_kline_df("600000.SH", 5000 * 60_000, 4980, 60_000)   # 4980 根（<5000）
    page2 = make_kline_df("600000.SH", 0, 20, 60_000)                 # 触及起点
    fake_tf.klines.queue(page1)
    fake_tf.klines.queue(page2)
    client = make_client(fake_tf)
    out = client.get_klines_range("600000.SH", "1m", 0, 10**13)
    assert len(out) == 5000
    assert len(fake_tf.klines.calls) == 2
    assert fake_tf.klines.calls[1]["end_time"] == page1["timestamp"].min() - 1


def test_empty_result_returns_empty_df(fake_tf):
    fake_tf.klines.queue(pd.DataFrame())
    client = make_client(fake_tf)
    out = client.get_klines_range("600000.SH", "1d", 1000, 4000)
    assert out.empty
    assert list(out.columns) == ["symbol", "timestamp", "open", "high", "low",
                                 "close", "volume", "amount"]


def test_list_universe_symbols(fake_tf):
    client = make_client(fake_tf)
    assert client.list_universe_symbols("CN_Equity_A") == ["600000.SH", "000001.SZ"]


def test_batch_range_continues_full_pages(fake_tf):
    df_full = make_kline_df("a.SH", 5000 * 60_000, 5000, 60_000)  # a.SH 满页需反向续拉
    df_full2 = make_kline_df("a.SH", 0, 10, 60_000)              # a.SH 触及起点
    df_short = make_kline_df("b.SH", 0, 100, 60_000)     # b.SH 一页拉完
    fake_tf.klines.batch_script = [{"a.SH": df_full, "b.SH": df_short},
                                   {"a.SH": df_full2}]
    client = make_client(fake_tf)
    out = client.get_klines_batch_range(["a.SH", "b.SH"], "1m", 0, 10**13)
    assert len(out) == 5000 + 10 + 100
    assert len(fake_tf.klines.batch_calls) == 2
    # 第二轮只续拉 a.SH，且 end_time 接续（反向）
    second = fake_tf.klines.batch_calls[1]
    assert second["symbols"] == ["a.SH"]
    assert second["end_time"] == df_full["timestamp"].min() - 1


def test_batch_range_empty(fake_tf):
    fake_tf.klines.batch_script = [{}]
    client = make_client(fake_tf)
    out = client.get_klines_batch_range(["a.SH"], "1d", 0, 10**9)
    assert out.empty


# ---- 加固①：分页进度守卫（异常服务端忽略 start_time，满页但时间戳不前进）----

def test_pagination_no_progress_breaks(fake_tf, caplog):
    # 满页且时间戳不向旧翻（min_ts > 已下移的 cursor）-> 第二页守卫断路
    page = make_kline_df("600000.SH", 5000 * 60_000, 5000, 60_000)  # min_ts=300M
    fake_tf.klines.fuse_after = 10  # 无守卫时保险丝快速熔断（防测试挂起）
    fake_tf.klines.queue_forever(page)  # 服务端永远返回同一满页
    client = make_client(fake_tf)
    with caplog.at_level(logging.WARNING):
        out = client.get_klines_range("600000.SH", "1m", 0, 10**13)
    assert len(out) == 5000
    assert len(fake_tf.klines.calls) == 2  # 第二页发现无进度即终止
    assert any("no progress" in r.getMessage() for r in caplog.records)


def test_batch_no_progress_breaks(fake_tf, caplog):
    page = make_kline_df("a.SH", 5000 * 60_000, 5000, 60_000)
    fake_tf.klines.fuse_after = 10
    fake_tf.klines.batch_queue_forever({"a.SH": page})
    client = make_client(fake_tf)
    with caplog.at_level(logging.WARNING):
        out = client.get_klines_batch_range(["a.SH"], "1m", 0, 10**13)
    assert len(out) == 5000
    assert len(fake_tf.klines.batch_calls) == 2  # 第二轮发现无进度即终止
    assert any("no progress" in r.getMessage() for r in caplog.records)


# ---- 加固②：classify_error 的 SDK isinstance 分支（真实 tickflow._exceptions 实例）----
# message 故意使用会误导字符串兜底的内容，以证明走的是 isinstance 分支。

def test_classify_error_sdk_rate_limit():
    from tickflow import _exceptions as tfe
    exc = tfe.RateLimitError("服务器内部错误", code="RATE_LIMIT", status_code=429)
    assert classify_error(exc) == "rate_limit"  # 字符串兜底会误判为 server


def test_classify_error_sdk_permission_is_client():
    from tickflow import _exceptions as tfe
    exc = tfe.PermissionError("429 too many requests", code="FORBIDDEN", status_code=403)
    assert classify_error(exc) == "client"  # 字符串兜底会误判为 rate_limit


def test_classify_error_sdk_client_family():
    from tickflow import _exceptions as tfe
    assert classify_error(tfe.BadRequestError("x", code="BAD", status_code=400)) == "client"
    assert classify_error(tfe.NotFoundError("x", code="NF", status_code=404)) == "client"
    assert classify_error(tfe.AuthenticationError("x", code="AUTH", status_code=401)) == "client"


def test_classify_error_sdk_server_family():
    from tickflow import _exceptions as tfe
    exc = tfe.InternalServerError("invalid symbol", code="INTERNAL", status_code=500)
    assert classify_error(exc) == "server"  # 字符串兜底会误判为 client
    assert classify_error(tfe.ConnectionError("network down")) == "server"
    assert classify_error(tfe.TimeoutError("too slow")) == "server"


def test_sdk_rate_limit_error_retried_then_raises(fake_tf):
    from tickflow import _exceptions as tfe
    for _ in range(3):
        fake_tf.klines.queue(tfe.RateLimitError("请求频率超限", code="RATE_LIMIT", status_code=429))
    client = make_client(fake_tf)
    with pytest.raises(RateLimitError):
        client.get_klines_range("600000.SH", "1d", 1000, 4000)
    assert len(fake_tf.klines.calls) == 3  # 限流可重试，耗尽后抛 RateLimitError


def test_sdk_permission_error_not_retried(fake_tf):
    from tickflow import _exceptions as tfe
    fake_tf.klines.queue(tfe.PermissionError("无分钟K线查询权限", code="FORBIDDEN", status_code=403))
    client = make_client(fake_tf)
    with pytest.raises(TickFlowError) as exc_info:
        client.get_klines_range("600000.SH", "1m", 1000, 4000)
    assert not isinstance(exc_info.value, RateLimitError)
    assert len(fake_tf.klines.calls) == 1  # client 类错误不重试


def test_get_ex_factors(fake_tf):
    fake_tf.klines.ex_factors.set([(1700000000000, 0.95)])
    client = make_client(fake_tf)
    assert client.get_ex_factors("600000.SH") == [(1700000000000, 0.95)]
