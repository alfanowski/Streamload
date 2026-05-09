"""In-memory playback session registry.

Sessions hold the upstream master URL + auth headers + (optional) DRM
keys, plus per-session segment cache state. They expire after TTL of
inactivity. State lives in process memory — for single-instance deploy.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PlaybackSession:
    id: uuid.UUID
    user_id: uuid.UUID
    tmdb_id: int
    service_short_name: str
    upstream_master_url: str
    upstream_headers: dict[str, str]
    is_drm: bool
    drm_keys: Optional[Any]
    created_at: float
    last_seen_at: float

    @classmethod
    def create(
        cls, *, user_id: uuid.UUID, tmdb_id: int, service_short_name: str,
        upstream_master_url: str, upstream_headers: dict[str, str],
        is_drm: bool = False, drm_keys: Optional[Any] = None,
    ) -> "PlaybackSession":
        now = time.time()
        return cls(
            id=uuid.uuid4(), user_id=user_id, tmdb_id=tmdb_id,
            service_short_name=service_short_name,
            upstream_master_url=upstream_master_url,
            upstream_headers=upstream_headers,
            is_drm=is_drm, drm_keys=drm_keys,
            created_at=now, last_seen_at=now,
        )


class PlaybackSessionRegistry:
    """Thread-safe in-memory session store with TTL eviction."""

    def __init__(self, *, ttl_seconds: int = 4 * 3600) -> None:
        self._ttl = ttl_seconds
        self._sessions: dict[uuid.UUID, PlaybackSession] = {}
        self._lock = threading.Lock()

    def put(self, session: PlaybackSession) -> None:
        with self._lock:
            self._sessions[session.id] = session

    def get(self, sid: uuid.UUID, *, touch: bool = False) -> Optional[PlaybackSession]:
        with self._lock:
            s = self._sessions.get(sid)
            if s is None:
                return None
            if time.time() - s.last_seen_at > self._ttl:
                self._sessions.pop(sid, None)
                return None
            if touch:
                s.last_seen_at = time.time()
            return s

    def purge_expired(self) -> int:
        now = time.time()
        purged = 0
        with self._lock:
            for sid, s in list(self._sessions.items()):
                if now - s.last_seen_at > self._ttl:
                    self._sessions.pop(sid, None)
                    purged += 1
        return purged

    def remove(self, sid: uuid.UUID) -> None:
        with self._lock:
            self._sessions.pop(sid, None)


# Module-level singleton
registry = PlaybackSessionRegistry()
