import time
import uuid

import pytest

from streamload.streaming.sessions import PlaybackSession, PlaybackSessionRegistry


def _make(**kw):
    defaults = dict(
        user_id=uuid.uuid4(), tmdb_id=42, service_short_name="sc",
        upstream_master_url="https://vix/x.m3u8",
        upstream_headers={"Referer": "https://vix"},
        is_drm=False, drm_keys=None,
    )
    defaults.update(kw)
    return PlaybackSession.create(**defaults)


def test_create_returns_session_with_id():
    s = _make()
    assert isinstance(s.id, uuid.UUID)
    assert s.tmdb_id == 42


def test_registry_get_returns_session():
    reg = PlaybackSessionRegistry(ttl_seconds=3600)
    s = _make()
    reg.put(s)
    assert reg.get(s.id) is s


def test_registry_get_unknown_returns_none():
    reg = PlaybackSessionRegistry(ttl_seconds=3600)
    assert reg.get(uuid.uuid4()) is None


def test_registry_get_expired_returns_none():
    reg = PlaybackSessionRegistry(ttl_seconds=-1)
    s = _make()
    reg.put(s)
    assert reg.get(s.id) is None


def test_registry_purge_removes_expired():
    reg = PlaybackSessionRegistry(ttl_seconds=-1)
    s = _make()
    reg.put(s)
    purged = reg.purge_expired()
    assert purged == 1
    assert s.id not in reg._sessions


def test_session_extends_on_touch():
    reg = PlaybackSessionRegistry(ttl_seconds=3600)
    s = _make()
    reg.put(s)
    before = s.last_seen_at
    time.sleep(0.01)
    s2 = reg.get(s.id, touch=True)
    assert s2.last_seen_at > before
