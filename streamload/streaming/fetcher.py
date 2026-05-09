"""Segment fetcher: RAM → disk → upstream → optional decrypt → cache."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional


class SegmentFetcher:
    def __init__(
        self,
        *,
        http: Any,
        ram: Any,
        disk: Any,
        decryptor: Optional[Callable[[bytes], bytes]] = None,
    ) -> None:
        self._http = http
        self._ram = ram
        self._disk = disk
        self._decryptor = decryptor

    async def fetch(self, key: str, *, upstream_url: str, headers: dict[str, str]) -> bytes:
        cached = self._ram.get(key)
        if cached is not None:
            return cached
        cached = self._disk.get(key)
        if cached is not None:
            self._ram.set(key, cached)
            return cached
        resp = await self._http.get(upstream_url, headers=headers)
        resp.raise_for_status()
        data = resp.content
        if self._decryptor is not None:
            data = self._decryptor(data)
        self._ram.set(key, data)
        self._disk.set(key, data, ttl_seconds=24 * 3600)
        return data
