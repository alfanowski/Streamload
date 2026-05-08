"""In-memory token-bucket rate limiter.

Designed for single-instance deployments. State lives in process memory
and resets on restart — appropriate for our single-server architecture.
For multi-instance deployments a Redis-backed limiter would replace this.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class RateLimiter:
    """A simple token bucket. ``rate`` tokens per ``per_seconds`` window."""

    def __init__(self, *, rate: int, per_seconds: float) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if per_seconds <= 0:
            raise ValueError("per_seconds must be > 0")
        self._rate = rate
        self._per = per_seconds
        self._refill_per_sec = rate / per_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        """Consume one token if available. Returns True if allowed."""
        now = time.monotonic()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=self._rate, last_refill=now)
                self._buckets[key] = b
            else:
                elapsed = now - b.last_refill
                b.tokens = min(self._rate, b.tokens + elapsed * self._refill_per_sec)
                b.last_refill = now
            if b.tokens >= 1:
                b.tokens -= 1
                return True
            return False

    def reset(self) -> None:
        """Clear all bucket state (used for test isolation)."""
        with self._lock:
            self._buckets.clear()

    def remaining(self, key: str) -> int:
        """Number of tokens currently available for *key* (without consuming)."""
        now = time.monotonic()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                return self._rate
            elapsed = now - b.last_refill
            tokens = min(self._rate, b.tokens + elapsed * self._refill_per_sec)
            return int(tokens)
