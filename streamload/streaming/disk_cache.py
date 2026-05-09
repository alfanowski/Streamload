"""Disk LRU cache for HLS segments backed by ``diskcache``."""
from __future__ import annotations

from typing import Optional

import diskcache


class SegmentCache:
    """Disk-backed LRU cache. Threadsafe, fork-safe."""

    def __init__(self, *, directory: str, size_limit_bytes: int) -> None:
        self._cache = diskcache.Cache(
            directory=directory,
            size_limit=size_limit_bytes,
            eviction_policy="least-recently-used",
        )

    def get(self, key: str) -> Optional[bytes]:
        return self._cache.get(key)

    def set(self, key: str, value: bytes, *, ttl_seconds: Optional[int] = None) -> None:
        self._cache.set(key, value, expire=ttl_seconds)

    def clear(self) -> None:
        self._cache.clear()

    def close(self) -> None:
        self._cache.close()
