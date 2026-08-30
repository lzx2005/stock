from datacenter.client.ratelimit import TokenBucket


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.slept = []
    def now(self):
        return self.t
    def sleep(self, secs):
        self.slept.append(secs)
        self.t += secs


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
