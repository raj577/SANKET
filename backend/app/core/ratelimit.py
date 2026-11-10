"""Small in-process rate limiter.

This is deliberately best-effort and per-process: it protects the login
endpoint from trivial brute force in a single-instance deployment. A shared
store (Redis) is the expected upgrade for horizontal scaling.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            bucket = self._events.setdefault(key, deque())
            cutoff = now - self.window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            if len(self._events) > 5000:
                for stale_key in [k for k, v in self._events.items() if not v or v[-1] < cutoff]:
                    self._events.pop(stale_key, None)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
