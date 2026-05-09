"""In-memory LRU ring buffer for hot segments per session."""
from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Optional


class RamRingBuffer:
    def __init__(self, *, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._cap = capacity
        self._d: OrderedDict[str, bytes] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> Optional[bytes]:
        with self._lock:
            v = self._d.get(key)
            if v is None:
                return None
            self._d.move_to_end(key)
            return v

    def set(self, key: str, value: bytes) -> None:
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
            self._d[key] = value
            while len(self._d) > self._cap:
                self._d.popitem(last=False)
