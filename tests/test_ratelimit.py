from tests.conftest import FakeClock
from datacenter.client.ratelimit import TokenBucket


def test_tokens_available_immediately_up_to_capacity():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_sec=10, now=clock.now, sleep=clock.sleep)
    for _ in range(10):  # 容量=1秒的速率，10 个立即可用
        bucket.acquire()
    assert clock.slept == []


def test_acquire_blocks_when_empty():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_sec=10, now=clock.now, sleep=clock.sleep)
    for _ in range(10):
        bucket.acquire()
    bucket.acquire()  # 第 11 个要等 0.1s
    assert clock.slept == [0.1]


def test_tokens_refill_over_time():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_sec=10, now=clock.now, sleep=clock.sleep)
    for _ in range(10):
        bucket.acquire()
    clock.t += 0.5  # 过了半秒，补 5 个
    for _ in range(5):
        bucket.acquire()
    assert clock.slept == []


def test_rate_below_one_still_acquires():
    # 回归：rate<1 时 capacity 需至少 1 个令牌，否则令牌永远凑不满 1 阈值、acquire 死循环
    clock = FakeClock()
    bucket = TokenBucket(rate_per_sec=0.5, now=clock.now, sleep=clock.sleep)
    bucket.acquire()          # 初始满令牌（burst≥1），立即通过
    assert clock.slept == []
    bucket.acquire()          # 已空，需等 2s 补 1 个令牌
    assert clock.slept == [2.0]
    bucket.acquire()          # 再等 2s
    assert clock.slept == [2.0, 2.0]
