"""In-memory token-bucket rate limiter."""
from __future__ import annotations

import time

import pytest

from streamload.auth.rate_limit import RateLimiter


def test_allows_within_limit():
    rl = RateLimiter(rate=5, per_seconds=60)
    for _ in range(5):
        assert rl.check("k") is True


def test_blocks_after_limit():
    rl = RateLimiter(rate=2, per_seconds=60)
    rl.check("k"); rl.check("k")
    assert rl.check("k") is False


def test_isolated_per_key():
    rl = RateLimiter(rate=1, per_seconds=60)
    assert rl.check("a") is True
    assert rl.check("b") is True


def test_refills_after_window():
    rl = RateLimiter(rate=2, per_seconds=0.1)
    rl.check("k"); rl.check("k")
    assert rl.check("k") is False
    time.sleep(0.15)
    assert rl.check("k") is True


def test_remaining_returns_correct_count():
    rl = RateLimiter(rate=5, per_seconds=60)
    rl.check("k"); rl.check("k")
    assert rl.remaining("k") == 3


def test_negative_rate_raises():
    with pytest.raises(ValueError):
        RateLimiter(rate=0, per_seconds=60)
