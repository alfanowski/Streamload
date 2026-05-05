"""In-memory per-service circuit breaker for domain failures.

Tracks consecutive failures since the last success. When the count crosses
*threshold* the breaker is open, signaling that the domain resolver should
invalidate its cache and re-resolve.

State is intentionally not persisted: a fresh process gets a clean slate,
so a brief outage doesn't keep a domain marked dead forever.
"""
from __future__ import annotations


class CircuitBreaker:
    def __init__(self, *, threshold: int = 3) -> None:
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        self._threshold = threshold
        self._failures: dict[str, int] = {}

    def record_failure(self, short_name: str) -> None:
        self._failures[short_name] = self._failures.get(short_name, 0) + 1

    def record_success(self, short_name: str) -> None:
        self._failures.pop(short_name, None)

    def reset(self, short_name: str) -> None:
        self._failures.pop(short_name, None)

    def is_open(self, short_name: str) -> bool:
        return self._failures.get(short_name, 0) >= self._threshold
