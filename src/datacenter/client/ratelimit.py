import threading
import time


class TokenBucket:
    """线程安全令牌桶。burst 上限 = 1 秒的速率，但至少 1 个令牌——
    否则 rate<1（如分钟批量档 0.5/s）时令牌被 capacity 卡在 1 以下，
    永远凑不满 acquire 的 1 令牌阈值，无限睡死。"""

    def __init__(self, rate_per_sec: float, now=time.monotonic, sleep=time.sleep):
        self._rate = rate_per_sec
        self._capacity = max(1.0, rate_per_sec)
        self._tokens = self._capacity
        self._last = now()
        self._now = now
        self._sleep = sleep
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._now()
                self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            self._sleep(wait)
