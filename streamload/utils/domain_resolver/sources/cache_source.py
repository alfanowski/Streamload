"""Source that reads a previously validated domain from the local cache."""
from __future__ import annotations

from ..cache import DomainCache
from .base import DomainSource


class CacheSource(DomainSource):
    """Returns the cached domain when its validated_at is within TTL."""

    name = "cache"

    def __init__(self, *, cache: DomainCache, ttl_seconds: int) -> None:
        self._cache = cache
        self._ttl = ttl_seconds

    def candidates(self, short_name: str) -> list[str]:
        if not self._cache.is_fresh(short_name, ttl_seconds=self._ttl):
            return []
        entry = self._cache.get(short_name)
        if entry is None:
            return []
        domain = entry.get("domain")
        return [domain] if domain else []
