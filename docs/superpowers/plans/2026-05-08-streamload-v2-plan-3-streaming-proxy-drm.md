# Streamload v2 — Plan 3: Streaming Proxy + DRM

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the HLS streaming proxy that lets the browser play any catalog title via `<video>` + hls.js, with server-side caching, DRM decryption for protected sources, and source switching mid-stream. By the end, calling `POST /api/play/{tmdb_id}` returns playback URLs that browsers can stream end-to-end.

**Architecture:** New `streamload/streaming/` package introduces a per-session playback context (held in memory, TTL 4h), an HLS master/media playlist rewriter (replaces upstream URLs with proxied URLs), an async segment fetcher with disk LRU + RAM ring buffer caches, a subtitle proxy that converts WebVTT, and a DRM decrypt layer that reuses existing `core/drm/` code for Widevine + PlayReady.

**Tech Stack:** Python 3.11+ async, FastAPI streaming responses, m3u8 parser (existing v1 `core/manifest/m3u8.py`), pywidevine + pyplayready (existing), aiofiles for async disk I/O, diskcache for LRU.

**Spec reference:** §6.3 (Streaming Proxy), §8 (Network & Streaming Architecture), §17 (cache directory layout).

**Prerequisite:** Plans 1 + 2 merged into main.

---

## File Structure

**New package — `streamload/streaming/`:**
- `__init__.py`
- `sessions.py` — in-memory `PlaybackSession` registry with TTL cleanup
- `m3u8_rewrite.py` — master + media playlist URL rewriting
- `vtt.py` — WebVTT passthrough/conversion
- `disk_cache.py` — `diskcache.Cache` wrapper for LRU segment storage
- `ram_buffer.py` — per-session in-memory recent-segment ring buffer
- `fetcher.py` — async segment fetcher (cache lookup → upstream → cache write)
- `drm.py` — wraps existing `core/drm/` for segment decrypt
- `service.py` — high-level orchestrator: build session, expose endpoints

**New API routes — `streamload/api/routes/`:**
- `play.py` — `POST /api/play/{tmdb_id}` (creates session)
- `stream.py` — `GET /stream/{session_id}/master.m3u8`, segment, subtitle endpoints

**Modified files:**
- `requirements.txt` — add `diskcache>=5.6`, `aiofiles>=24`
- `streamload/api/app.py` — include new routers, add lifespan hook for cache init
- `streamload/utils/config.py` — extend `streaming` section
- `streamload/version.py` — bump

**New tests — `tests/streaming/`:**
- `test_sessions.py`, `test_m3u8_rewrite.py`, `test_vtt.py`, `test_disk_cache.py`,
  `test_ram_buffer.py`, `test_fetcher.py`, `test_drm.py`, `test_service.py`
- `tests/api/test_play.py`, `tests/api/test_stream.py`

---

## Conventions

- Branch: `feat/v2-streaming-proxy-drm`
- TDD strict; conventional commits; **no `Co-Authored-By`**
- All new code async; sync-only is a smell

---

## Task 0: Branch + dependencies

- [ ] Branch + deps:

```bash
git checkout main && git pull
git checkout -b feat/v2-streaming-proxy-drm

# requirements.txt — append:
# diskcache>=5.6
# aiofiles>=24

venv/bin/pip install -r requirements.txt
git add requirements.txt
git commit -m "chore: add diskcache + aiofiles for streaming proxy"
```

---

## Task 1: PlaybackSession registry

**Files:** `streamload/streaming/__init__.py`, `streamload/streaming/sessions.py`, `tests/streaming/__init__.py`, `tests/streaming/test_sessions.py`

- [ ] **Failing test** `tests/streaming/test_sessions.py`:

```python
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
```

- [ ] Run, expect FAIL.

- [ ] Implement `streamload/streaming/__init__.py`:

```python
"""Streaming proxy package."""
from __future__ import annotations
```

- [ ] Implement `streamload/streaming/sessions.py`:

```python
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
```

- [ ] Run, expect 6 passed. Commit:

```bash
git add streamload/streaming/__init__.py streamload/streaming/sessions.py tests/streaming/__init__.py tests/streaming/test_sessions.py
git commit -m "feat(streaming): playback session registry with TTL"
```

---

## Task 2: HLS master + media playlist rewriter

**Files:** `streamload/streaming/m3u8_rewrite.py`, `tests/streaming/test_m3u8_rewrite.py`

- [ ] Failing test:

```python
"""HLS master + media playlist URL rewriting."""
from streamload.streaming.m3u8_rewrite import rewrite_master, rewrite_media

MASTER_SAMPLE = """\
#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Italian",DEFAULT=YES,LANGUAGE="ita",URI="https://upstream/playlist?type=audio&rendition=ita&token=t1"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Italian",LANGUAGE="ita",URI="https://upstream/playlist?type=subtitle&rendition=ita&token=t1"
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=854x480,AUDIO="audio",SUBTITLES="subs"
https://upstream/playlist?type=video&rendition=480p&token=t1
#EXT-X-STREAM-INF:BANDWIDTH=2150000,RESOLUTION=1280x720,AUDIO="audio",SUBTITLES="subs"
https://upstream/playlist?type=video&rendition=720p&token=t1
"""

MEDIA_SAMPLE = """\
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXTINF:5.5,
https://upstream/seg-001.ts
#EXTINF:5.5,
https://upstream/seg-002.ts
#EXT-X-ENDLIST
"""


def test_rewrite_master_replaces_video_renditions():
    out = rewrite_master(MASTER_SAMPLE, session_id="sid", base_path="/stream/sid")
    assert "/stream/sid/video/480p.m3u8" in out
    assert "/stream/sid/video/720p.m3u8" in out
    assert "upstream" not in out


def test_rewrite_master_replaces_audio_uris():
    out = rewrite_master(MASTER_SAMPLE, session_id="sid", base_path="/stream/sid")
    assert "/stream/sid/audio/ita.m3u8" in out
    assert "upstream" not in out


def test_rewrite_master_replaces_subtitle_uris():
    out = rewrite_master(MASTER_SAMPLE, session_id="sid", base_path="/stream/sid")
    assert "/stream/sid/sub/ita.vtt" in out


def test_rewrite_master_preserves_stream_inf_attributes():
    out = rewrite_master(MASTER_SAMPLE, session_id="sid", base_path="/stream/sid")
    assert "BANDWIDTH=1200000" in out
    assert "RESOLUTION=854x480" in out


def test_rewrite_media_replaces_segment_urls():
    out = rewrite_media(MEDIA_SAMPLE, session_id="sid", rendition="720p",
                        base_path="/stream/sid")
    assert "/stream/sid/seg/720p/0.ts" in out
    assert "/stream/sid/seg/720p/1.ts" in out
    assert "upstream" not in out


def test_rewrite_media_preserves_extinf_durations():
    out = rewrite_media(MEDIA_SAMPLE, session_id="sid", rendition="720p",
                        base_path="/stream/sid")
    assert "#EXTINF:5.5" in out
    assert "#EXT-X-ENDLIST" in out
```

- [ ] Run FAIL. Implement:

```python
"""HLS master + media playlist URL rewriting.

Rewrites in two passes:

1. ``rewrite_master(text, session_id, base_path)`` — replaces every
   stream-inf, audio, and subtitle URI to point at our backend's
   `/stream/{session_id}/...` proxy paths. Strips upstream tokens
   from URLs returned to the browser.

2. ``rewrite_media(text, session_id, rendition, base_path)`` — replaces
   each segment URI with `/stream/{session_id}/seg/{rendition}/{n}.ts`.

The mapping from rendition label (e.g. "480p") to upstream URL is
maintained server-side in the playback session.
"""
from __future__ import annotations

import re

_STREAM_INF_RE = re.compile(r"^#EXT-X-STREAM-INF:.*?$", re.MULTILINE)
_RESOLUTION_RE = re.compile(r"RESOLUTION=(\d+)x(\d+)")
_RENDITION_PARAM_RE = re.compile(r"rendition=([^&\"\s]+)")
_AUDIO_LANG_RE = re.compile(r'LANGUAGE="([^"]+)".*?URI="[^"]+"', re.DOTALL)
_URI_ATTR_RE = re.compile(r'URI="([^"]+)"')


def _label_for_rendition(url: str) -> str:
    """Extract a stable label from the upstream URL — prefers ``rendition=`` query param."""
    m = _RENDITION_PARAM_RE.search(url)
    if m:
        return m.group(1)
    # Fallback: use a hash of the URL
    import hashlib
    return hashlib.sha1(url.encode()).hexdigest()[:8]


def rewrite_master(text: str, *, session_id: str, base_path: str) -> str:
    """Replace upstream URLs in a master playlist with our proxy paths."""
    out_lines: list[str] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Audio/Subtitle media tags carry URI in attributes
        if line.startswith("#EXT-X-MEDIA:"):
            uri_m = _URI_ATTR_RE.search(line)
            type_m = re.search(r"TYPE=(\w+)", line)
            lang_m = re.search(r'LANGUAGE="([^"]+)"', line)
            if uri_m and type_m and lang_m:
                lang = lang_m.group(1)
                if type_m.group(1) == "AUDIO":
                    new_uri = f"{base_path}/audio/{lang}.m3u8"
                elif type_m.group(1) == "SUBTITLES":
                    new_uri = f"{base_path}/sub/{lang}.vtt"
                else:
                    new_uri = uri_m.group(1)
                line = line[:uri_m.start()] + f'URI="{new_uri}"' + line[uri_m.end():]
            out_lines.append(line)
            i += 1
            continue

        # STREAM-INF is followed by a URI on the next line
        if line.startswith("#EXT-X-STREAM-INF:"):
            out_lines.append(line)
            i += 1
            if i < len(lines):
                upstream_url = lines[i].strip()
                if upstream_url and not upstream_url.startswith("#"):
                    label = _label_for_rendition(upstream_url)
                    out_lines.append(f"{base_path}/video/{label}.m3u8")
                    i += 1
                    continue
            continue

        out_lines.append(line)
        i += 1

    return "\n".join(out_lines)


def rewrite_media(text: str, *, session_id: str, rendition: str, base_path: str) -> str:
    """Replace segment URIs in a media playlist."""
    out_lines: list[str] = []
    seg_index = 0
    for line in text.split("\n"):
        # Segment URLs are non-comment, non-empty lines
        if line and not line.startswith("#"):
            out_lines.append(f"{base_path}/seg/{rendition}/{seg_index}.ts")
            seg_index += 1
            continue
        out_lines.append(line)
    return "\n".join(out_lines)
```

- [ ] Run PASS, commit:

```bash
git add streamload/streaming/m3u8_rewrite.py tests/streaming/test_m3u8_rewrite.py
git commit -m "feat(streaming): HLS master + media playlist rewriter"
```

---

## Task 3: Disk LRU cache

**Files:** `streamload/streaming/disk_cache.py`, `tests/streaming/test_disk_cache.py`

- [ ] Failing test:

```python
"""Disk LRU segment cache."""
import pytest
from pathlib import Path

from streamload.streaming.disk_cache import SegmentCache


def test_set_then_get_roundtrip(tmp_path: Path):
    c = SegmentCache(directory=str(tmp_path), size_limit_bytes=10*1024*1024)
    c.set("k1", b"hello world")
    assert c.get("k1") == b"hello world"


def test_get_missing_returns_none(tmp_path: Path):
    c = SegmentCache(directory=str(tmp_path), size_limit_bytes=10*1024*1024)
    assert c.get("k_missing") is None


def test_lru_evicts_when_full(tmp_path: Path):
    c = SegmentCache(directory=str(tmp_path), size_limit_bytes=200)  # tiny
    c.set("a", b"a" * 100)
    c.set("b", b"b" * 100)
    c.set("c", b"c" * 100)  # forces eviction
    # Some keys evicted; total below limit
    keys_present = [k for k in ("a", "b", "c") if c.get(k) is not None]
    assert len(keys_present) <= 2


def test_clear(tmp_path: Path):
    c = SegmentCache(directory=str(tmp_path), size_limit_bytes=10*1024*1024)
    c.set("x", b"y")
    c.clear()
    assert c.get("x") is None
```

- [ ] Implement:

```python
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
```

- [ ] Run + commit `feat(streaming): disk LRU cache for segments`.

---

## Task 4: RAM ring buffer

**Files:** `streamload/streaming/ram_buffer.py`, `tests/streaming/test_ram_buffer.py`

- [ ] Failing test:

```python
from streamload.streaming.ram_buffer import RamRingBuffer


def test_set_get_within_capacity():
    rb = RamRingBuffer(capacity=3)
    rb.set("a", b"1")
    rb.set("b", b"2")
    assert rb.get("a") == b"1"
    assert rb.get("b") == b"2"


def test_evicts_oldest_when_full():
    rb = RamRingBuffer(capacity=2)
    rb.set("a", b"1"); rb.set("b", b"2"); rb.set("c", b"3")
    assert rb.get("a") is None
    assert rb.get("b") == b"2"
    assert rb.get("c") == b"3"


def test_get_nonexistent_returns_none():
    rb = RamRingBuffer(capacity=2)
    assert rb.get("x") is None


def test_get_promotes_to_recent():
    rb = RamRingBuffer(capacity=2)
    rb.set("a", b"1"); rb.set("b", b"2")
    rb.get("a")  # touches a
    rb.set("c", b"3")  # should evict b, not a
    assert rb.get("a") == b"1"
    assert rb.get("b") is None
```

- [ ] Implement:

```python
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
```

- [ ] Run + commit `feat(streaming): RAM ring buffer for hot segments`.

---

## Task 5: Segment fetcher

**Files:** `streamload/streaming/fetcher.py`, `tests/streaming/test_fetcher.py`

The fetcher is the meat: cache lookup → upstream fetch with referer → optional DRM decrypt → cache write → return bytes.

- [ ] Failing test (mocked):

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from streamload.streaming.fetcher import SegmentFetcher


def _ok(bytes_: bytes):
    r = MagicMock()
    r.status_code = 200
    r.content = bytes_
    r.raise_for_status = MagicMock()
    return r


@pytest.mark.asyncio
async def test_fetch_hits_ram_cache_first():
    http = MagicMock()
    http.get = AsyncMock(return_value=_ok(b"upstream"))
    ram = MagicMock()
    ram.get = MagicMock(return_value=b"ram-hit")
    disk = MagicMock()
    f = SegmentFetcher(http=http, ram=ram, disk=disk)
    out = await f.fetch("k", upstream_url="https://x", headers={})
    assert out == b"ram-hit"
    http.get.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_falls_through_to_disk():
    http = MagicMock()
    http.get = AsyncMock()
    ram = MagicMock()
    ram.get = MagicMock(return_value=None)
    ram.set = MagicMock()
    disk = MagicMock()
    disk.get = MagicMock(return_value=b"disk-hit")
    f = SegmentFetcher(http=http, ram=ram, disk=disk)
    out = await f.fetch("k", upstream_url="https://x", headers={})
    assert out == b"disk-hit"
    ram.set.assert_called_once_with("k", b"disk-hit")
    http.get.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_misses_both_caches_goes_upstream():
    http = MagicMock()
    http.get = AsyncMock(return_value=_ok(b"upstream-bytes"))
    ram = MagicMock(); ram.get = MagicMock(return_value=None); ram.set = MagicMock()
    disk = MagicMock(); disk.get = MagicMock(return_value=None); disk.set = MagicMock()
    f = SegmentFetcher(http=http, ram=ram, disk=disk)
    out = await f.fetch("k", upstream_url="https://x", headers={"Referer": "r"})
    assert out == b"upstream-bytes"
    ram.set.assert_called_once_with("k", b"upstream-bytes")
    disk.set.assert_called_once()
    http.get.assert_called_once_with("https://x", headers={"Referer": "r"})


@pytest.mark.asyncio
async def test_fetch_decrypts_when_decryptor_provided():
    http = MagicMock(); http.get = AsyncMock(return_value=_ok(b"encrypted"))
    ram = MagicMock(); ram.get = MagicMock(return_value=None); ram.set = MagicMock()
    disk = MagicMock(); disk.get = MagicMock(return_value=None); disk.set = MagicMock()
    decryptor = MagicMock(return_value=b"plaintext")
    f = SegmentFetcher(http=http, ram=ram, disk=disk, decryptor=decryptor)
    out = await f.fetch("k", upstream_url="https://x", headers={})
    assert out == b"plaintext"
    decryptor.assert_called_once_with(b"encrypted")
    # The cached value is the *decrypted* one (we never want to re-decrypt)
    ram.set.assert_called_once_with("k", b"plaintext")
```

- [ ] Implement:

```python
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
```

- [ ] Run + commit `feat(streaming): segment fetcher with cache hierarchy`.

---

## Task 6: WebVTT subtitle proxy

**Files:** `streamload/streaming/vtt.py`, `tests/streaming/test_vtt.py`

- [ ] Failing test:

```python
from streamload.streaming.vtt import is_webvtt, srt_to_vtt


def test_detects_webvtt_header():
    assert is_webvtt("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhi\n")


def test_rejects_non_webvtt():
    assert not is_webvtt("1\n00:00:01,000 --> 00:00:02,000\nhi")


def test_srt_converts_to_vtt():
    srt = "1\n00:00:01,500 --> 00:00:03,000\nCiao mondo\n\n2\n00:00:04,000 --> 00:00:05,000\nFine\n"
    out = srt_to_vtt(srt)
    assert out.startswith("WEBVTT")
    assert "00:00:01.500 --> 00:00:03.000" in out
    assert "Ciao mondo" in out
```

- [ ] Implement:

```python
"""WebVTT detection + SRT→VTT conversion (browsers want VTT)."""
from __future__ import annotations

import re


def is_webvtt(text: str) -> bool:
    return text.strip().startswith("WEBVTT")


_SRT_TIMING_RE = re.compile(r"(\d{2}:\d{2}:\d{2}),(\d{3})")


def srt_to_vtt(srt: str) -> str:
    """Minimal SRT to WebVTT conversion (timing comma → dot, prepend header)."""
    body = _SRT_TIMING_RE.sub(r"\1.\2", srt)
    return "WEBVTT\n\n" + body
```

- [ ] Run + commit `feat(streaming): WebVTT detection + SRT conversion`.

---

## Task 7: DRM wrapper

**Files:** `streamload/streaming/drm.py`, `tests/streaming/test_drm.py`

The existing `streamload/core/drm/` already has Widevine + PlayReady CDMs. We wrap them in a per-session decryptor.

- [ ] Failing test (mocked):

```python
from unittest.mock import MagicMock
from streamload.streaming.drm import build_decryptor


def test_build_decryptor_uses_keys_to_decrypt():
    # Provide a mocked low-level decrypt fn
    keys = [{"kid": "x", "key": "y"}]
    raw = b"ciphertext"
    fake_decrypt = MagicMock(return_value=b"plaintext")
    dec = build_decryptor(keys=keys, _decrypt_fn=fake_decrypt)
    out = dec(raw)
    assert out == b"plaintext"
    fake_decrypt.assert_called_once_with(raw, keys)


def test_build_decryptor_returns_none_when_no_keys():
    dec = build_decryptor(keys=None)
    assert dec is None
```

- [ ] Implement (delegates to existing v1 DRM code):

```python
"""DRM segment decryption wrapper.

For DRM-protected content, the v1 ``streamload.core.drm`` module already
extracts content keys via the CDM (Widevine L3 / PlayReady L3). This
module wraps the resulting keys in a callable that decrypts a single
segment's bytes — suitable for use by the ``SegmentFetcher.decryptor``
parameter.

The default ``_decrypt_fn`` calls into ``core.drm.decrypt.decrypt_segment``
(existing). Tests can inject a mock.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


def _real_decrypt(raw: bytes, keys: Any) -> bytes:
    # Import lazily to avoid hard dependency in tests.
    from streamload.core.drm.decrypt import decrypt_segment
    return decrypt_segment(raw, keys=keys)


def build_decryptor(
    *, keys: Optional[Any], _decrypt_fn: Callable[[bytes, Any], bytes] = _real_decrypt,
) -> Optional[Callable[[bytes], bytes]]:
    """Return a callable bytes->bytes that decrypts using *keys*. None if no DRM."""
    if not keys:
        return None
    def decrypt(raw: bytes) -> bytes:
        return _decrypt_fn(raw, keys)
    return decrypt
```

(Note: the actual `decrypt_segment` function may already exist in `core/drm/decrypt.py` — if not, this task ALSO needs a minimal AES-128-CTR/CBC implementation. Verify by running `grep -n "def decrypt_segment" streamload/core/drm/`.)

- [ ] Run + commit `feat(streaming): DRM segment decryptor wrapper`.

---

## Task 8: Playback service orchestrator

**Files:** `streamload/streaming/service.py`, `tests/streaming/test_service.py`

Builds the upstream HLS playlist, creates a session, registers it.

- [ ] Failing test (mocked v1 service):

```python
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from streamload.streaming.service import build_playback_session


@pytest.mark.asyncio
async def test_build_session_for_non_drm_movie():
    bundle = MagicMock()
    bundle.manifest_url = "https://upstream/master.m3u8"
    bundle.extra_headers = {"Referer": "https://upstream"}
    bundle.is_drm = False
    bundle.drm_keys = None
    bundle.subtitles = []

    fake_service = MagicMock()
    fake_service.short_name = "sc"
    fake_service.get_streams_async = AsyncMock(return_value=bundle)

    sess = await build_playback_session(
        user_id=uuid.uuid4(), tmdb_id=42, service=fake_service, media_id="m1",
    )
    assert sess.is_drm is False
    assert sess.upstream_master_url.startswith("https://upstream")


@pytest.mark.asyncio
async def test_build_session_for_drm_keeps_keys():
    bundle = MagicMock()
    bundle.manifest_url = "https://upstream/master.m3u8"
    bundle.extra_headers = {}
    bundle.is_drm = True
    bundle.drm_keys = [{"kid": "x", "key": "y"}]

    fake_service = MagicMock()
    fake_service.short_name = "rp"
    fake_service.get_streams_async = AsyncMock(return_value=bundle)

    sess = await build_playback_session(
        user_id=uuid.uuid4(), tmdb_id=42, service=fake_service, media_id="m1",
    )
    assert sess.is_drm is True
    assert sess.drm_keys == [{"kid": "x", "key": "y"}]
```

- [ ] Implement:

```python
"""Playback orchestrator: from canonical title → registered PlaybackSession."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from streamload.utils.logger import get_logger

from .sessions import PlaybackSession, registry

log = get_logger(__name__)


async def build_playback_session(
    *,
    user_id: uuid.UUID,
    tmdb_id: int,
    service: Any,
    media_id: str,
    episode_id: Optional[str] = None,
) -> PlaybackSession:
    """Resolve the upstream HLS bundle and register a playback session."""
    if hasattr(service, "get_streams_async"):
        bundle = await service.get_streams_async(media_id)
    else:
        import asyncio
        bundle = await asyncio.to_thread(service.get_streams, media_id)

    sess = PlaybackSession.create(
        user_id=user_id,
        tmdb_id=tmdb_id,
        service_short_name=service.short_name,
        upstream_master_url=bundle.manifest_url,
        upstream_headers=getattr(bundle, "extra_headers", {}) or {},
        is_drm=getattr(bundle, "is_drm", False),
        drm_keys=getattr(bundle, "drm_keys", None),
    )
    registry.put(sess)
    log.info("Created playback session %s (tmdb=%s service=%s drm=%s)",
             sess.id, tmdb_id, service.short_name, sess.is_drm)
    return sess
```

- [ ] Run + commit.

---

## Task 9: `POST /api/play/{tmdb_id}` route

**Files:** `streamload/api/routes/play.py`, `tests/api/test_play.py`

- [ ] Failing test:

```python
"""Playback session creation endpoint."""
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem, CatalogSource


@pytest.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "u", "email": "u@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_play_creates_session(api_client, authed):
    async for db in gs():
        db.add(CatalogItem(tmdb_id=42, media_type="movie", title="X", year=2024))
        db.add(CatalogSource(
            tmdb_id=42, service_short_name="sc", service_url="https://sc/42",
            service_media_id="42", quality_max_height=1080,
        ))
        await db.commit()
        break

    bundle = MagicMock()
    bundle.manifest_url = "https://vix/master.m3u8"
    bundle.extra_headers = {}
    bundle.is_drm = False
    bundle.drm_keys = None
    bundle.subtitles = []

    with patch("streamload.api.routes.play._get_service") as mk:
        svc = MagicMock()
        svc.short_name = "sc"
        svc.get_streams_async = AsyncMock(return_value=bundle)
        mk.return_value = svc
        r = await api_client.post("/api/play/42")
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert body["master_url"].startswith("/stream/")
    assert body["current_server"] == "Server 1"


@pytest.mark.asyncio
async def test_play_unknown_title_404(api_client, authed):
    r = await api_client.post("/api/play/9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_play_requires_email_verified(api_client):
    # Register, but DON'T verify
    await api_client.post("/api/auth/register", json={
        "username": "u", "email": "u@x.com", "password": "Hunter2!secret",
    })
    async for db in gs():
        db.add(CatalogItem(tmdb_id=42, media_type="movie", title="X"))
        db.add(CatalogSource(
            tmdb_id=42, service_short_name="sc", service_url="https://sc/42",
            service_media_id="42",
        ))
        await db.commit()
        break
    r = await api_client.post("/api/play/42")
    assert r.status_code == 403
    assert "email" in r.json()["detail"].lower()
```

- [ ] Run FAIL. Implement:

```python
"""Playback session endpoint."""
from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import CurrentUser, SessionDep
from streamload.catalog.ranker import SourceMetrics, rank_sources
from streamload.catalog.service import CatalogService
from streamload.db.models import CatalogItem, CatalogSource
from streamload.streaming.service import build_playback_session

router = APIRouter(prefix="/play", tags=["play"])


class ServerOption(BaseModel):
    label: str
    score: float


class PlaybackResponse(BaseModel):
    session_id: str
    master_url: str
    current_server: str
    available_servers: list[ServerOption]


def _get_service(short_name: str) -> Any:
    """Lookup an instantiated service plugin by short_name."""
    from streamload.services import ServiceRegistry, load_services
    from streamload.utils.http import HttpClient
    load_services()
    cls = ServiceRegistry.get_by_short_name(short_name)
    if cls is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"service {short_name!r} not registered")
    return cls(HttpClient())


@router.post("/{tmdb_id}", response_model=PlaybackResponse)
async def start_playback(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
    server: str | None = Query(default=None),  # 'auto' or 'Server 1' style
) -> PlaybackResponse:
    if user.email_verified_at is None and user.email_required:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "email not verified")

    svc = CatalogService(db)
    item = await svc.get_item(tmdb_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "title not in catalog")
    if not item.sources:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no sources available for title")

    metrics = [
        SourceMetrics(
            service_short_name=s.service_short_name,
            service_url=s.service_url,
            service_media_id=s.service_media_id,
            quality_max_height=s.quality_max_height,
            latency_ttfb_ms=None,
            success_count=s.success_count,
            failure_count=s.failure_count,
            audio_languages=s.languages_audio,
            subtitle_languages=s.languages_subs,
            last_verified_at=s.last_verified_at,
        ) for s in item.sources
    ]
    ranked = rank_sources(metrics, user_audio_pref="ita", user_subs_pref="ita")

    chosen = ranked[0]  # default Server 1
    if server:
        for r in ranked:
            if r.label == server:
                chosen = r
                break

    service = _get_service(chosen.metrics.service_short_name)
    sess = await build_playback_session(
        user_id=user.id, tmdb_id=tmdb_id, service=service,
        media_id=chosen.metrics.service_media_id,
    )
    return PlaybackResponse(
        session_id=str(sess.id),
        master_url=f"/stream/{sess.id}/master.m3u8",
        current_server=chosen.label,
        available_servers=[ServerOption(label=r.label, score=r.score) for r in ranked],
    )
```

- [ ] Wire in `app.py`:

```python
from .routes import auth, catalog, collections, email, health, me, passkey, play, search
app.include_router(play.router, prefix="/api")
```

- [ ] Run + commit `feat(api): POST /api/play/{tmdb_id} creates streaming session`.

---

## Task 10: `/stream/...` proxy routes

**Files:** `streamload/api/routes/stream.py`, `tests/api/test_stream.py`

The stream routes are NOT under `/api/` (HLS players don't carry cookies for cross-origin, and we want the path obvious). They live at `/stream/...`.

- [ ] Failing test:

```python
"""HLS proxy endpoints."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from streamload.streaming.sessions import PlaybackSession, registry


@pytest.fixture
async def authed_session(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "u", "email": "u@x.com", "password": "Hunter2!secret",
    })
    sess = PlaybackSession.create(
        user_id=uuid.uuid4(), tmdb_id=42, service_short_name="sc",
        upstream_master_url="https://up/master.m3u8",
        upstream_headers={"Referer": "https://up"},
    )
    registry.put(sess)
    return sess


@pytest.mark.asyncio
async def test_master_returns_rewritten_playlist(api_client, authed_session):
    upstream_text = (
        "#EXTM3U\n"
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="It",LANGUAGE="ita",URI="https://up/audio?token=x"\n'
        "#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720\n"
        "https://up/playlist?type=video&rendition=720p&token=x\n"
    )
    fake_resp = MagicMock(); fake_resp.status_code = 200; fake_resp.text = upstream_text
    fake_resp.raise_for_status = MagicMock()
    with patch("streamload.api.routes.stream._fetch_upstream_text", return_value=upstream_text):
        r = await api_client.get(f"/stream/{authed_session.id}/master.m3u8")
    assert r.status_code == 200
    assert "#EXTM3U" in r.text
    assert f"/stream/{authed_session.id}/" in r.text
    assert "https://up" not in r.text


@pytest.mark.asyncio
async def test_master_unknown_session_returns_404(api_client):
    r = await api_client.get(f"/stream/{uuid.uuid4()}/master.m3u8")
    assert r.status_code == 404
```

- [ ] Implement (key points only):

```python
"""HLS proxy: master, media, segment, subtitle endpoints."""
from __future__ import annotations

import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Response, status

from streamload.streaming.m3u8_rewrite import rewrite_master, rewrite_media
from streamload.streaming.sessions import registry

router = APIRouter(prefix="/stream", tags=["stream"])


async def _fetch_upstream_text(url: str, headers: dict[str, str]) -> str:
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(url, headers=headers)
        r.raise_for_status()
        return r.text


@router.get("/{session_id}/master.m3u8")
async def proxy_master(session_id: uuid.UUID) -> Response:
    sess = registry.get(session_id, touch=True)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session expired or unknown")
    upstream_text = await _fetch_upstream_text(sess.upstream_master_url, sess.upstream_headers)
    rewritten = rewrite_master(
        upstream_text, session_id=str(session_id),
        base_path=f"/stream/{session_id}",
    )
    return Response(rewritten, media_type="application/x-mpegURL")


@router.get("/{session_id}/video/{rendition}.m3u8")
async def proxy_media_video(session_id: uuid.UUID, rendition: str) -> Response:
    sess = registry.get(session_id, touch=True)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # The session knows the master; we re-fetch it to find the upstream rendition URL.
    master_text = await _fetch_upstream_text(sess.upstream_master_url, sess.upstream_headers)
    # Find the upstream URL for this rendition label
    upstream_rendition_url: Optional[str] = None
    lines = master_text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:") and i + 1 < len(lines):
            url = lines[i+1].strip()
            if rendition in url:
                upstream_rendition_url = url
                break
    if upstream_rendition_url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rendition {rendition} not in master")
    media_text = await _fetch_upstream_text(upstream_rendition_url, sess.upstream_headers)
    rewritten = rewrite_media(
        media_text, session_id=str(session_id), rendition=rendition,
        base_path=f"/stream/{session_id}",
    )
    return Response(rewritten, media_type="application/x-mpegURL")


# Segment + subtitle endpoints follow the same pattern. Full code in the
# implementation; for brevity here we list the signatures:

@router.get("/{session_id}/seg/{rendition}/{n}.ts")
async def proxy_segment(session_id: uuid.UUID, rendition: str, n: int) -> Response:
    """Fetch segment N for the given rendition, with cache + DRM decrypt."""
    sess = registry.get(session_id, touch=True)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # Resolve the upstream segment URL by re-parsing the rendition playlist.
    # In production, the session caches the parsed segment list; for v1 we
    # re-fetch (cheap because the playlist is in disk cache).
    master_text = await _fetch_upstream_text(sess.upstream_master_url, sess.upstream_headers)
    rendition_url: Optional[str] = None
    for line in master_text.split("\n"):
        if not line.startswith("#") and rendition in line:
            rendition_url = line.strip()
            break
    if rendition_url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    media_text = await _fetch_upstream_text(rendition_url, sess.upstream_headers)
    seg_urls = [l.strip() for l in media_text.split("\n") if l and not l.startswith("#")]
    if n >= len(seg_urls):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    upstream_seg = seg_urls[n]

    # Use SegmentFetcher singletons (initialized in lifespan)
    from streamload.api.app import seg_fetcher_for_session  # injected
    fetcher = seg_fetcher_for_session(session_id)
    cache_key = f"{session_id}:{rendition}:{n}"
    data = await fetcher.fetch(cache_key, upstream_url=upstream_seg, headers=sess.upstream_headers)
    return Response(data, media_type="video/mp2t")


@router.get("/{session_id}/sub/{lang}.vtt")
async def proxy_subtitle(session_id: uuid.UUID, lang: str) -> Response:
    """Proxy + convert subtitle stream to WebVTT."""
    sess = registry.get(session_id, touch=True)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    master_text = await _fetch_upstream_text(sess.upstream_master_url, sess.upstream_headers)
    # Find subtitle URI for lang
    sub_url: Optional[str] = None
    for line in master_text.split("\n"):
        if line.startswith("#EXT-X-MEDIA:") and "TYPE=SUBTITLES" in line and f'LANGUAGE="{lang}"' in line:
            import re
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                sub_url = m.group(1)
                break
    if sub_url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    text = await _fetch_upstream_text(sub_url, sess.upstream_headers)
    from streamload.streaming.vtt import is_webvtt, srt_to_vtt
    if not is_webvtt(text):
        text = srt_to_vtt(text)
    return Response(text, media_type="text/vtt")
```

- [ ] Add `seg_fetcher_for_session` factory in `app.py` lifespan.

- [ ] Wire `stream.router` (NOT under `/api/`):

```python
# in create_app:
app.include_router(stream.router)  # mounted at /stream
```

- [ ] Run + commit `feat(api): HLS proxy endpoints (master/media/segment/subtitle)`.

---

## Task 11: Quality probing of catalog sources

When we fetch the master playlist for the first time, we know the highest available `RESOLUTION=` — persist it in `catalog_sources.quality_max_height` so future ranking is informed.

**Files:** `streamload/streaming/quality_probe.py`, `tests/streaming/test_quality_probe.py`

- [ ] Failing test:

```python
from streamload.streaming.quality_probe import max_height_from_master


def test_extracts_max_resolution():
    master = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=854x480\nhttps://x/480p\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=2150000,RESOLUTION=1280x720\nhttps://x/720p\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=4500000,RESOLUTION=1920x1080\nhttps://x/1080p\n"
    )
    assert max_height_from_master(master) == 1080


def test_returns_none_when_no_resolution():
    master = "#EXTM3U\n#EXT-X-VERSION:3\n"
    assert max_height_from_master(master) is None
```

- [ ] Implement:

```python
"""Extract maximum video resolution from an HLS master playlist."""
from __future__ import annotations

import re
from typing import Optional

_RES_RE = re.compile(r"RESOLUTION=\d+x(\d+)")


def max_height_from_master(text: str) -> Optional[int]:
    heights = [int(m.group(1)) for m in _RES_RE.finditer(text)]
    return max(heights) if heights else None
```

- [ ] Hook into `proxy_master` to update `catalog_sources.quality_max_height` on first hit per session.

- [ ] Run + commit.

---

## Task 12: End-to-end streaming smoke

**Files:** `tests/api/test_stream_e2e.py`

- [ ] Write E2E test that:
  1. Registers + verifies user
  2. Inserts a catalog item + source
  3. Mocks the v1 service `get_streams_async` to return a fake bundle
  4. Mocks `_fetch_upstream_text` to return realistic HLS text
  5. POST /api/play/{tmdb_id} → get session
  6. GET /stream/{session}/master.m3u8 → assert rewritten
  7. GET /stream/{session}/seg/720p/0.ts → assert returns bytes (mocked)

This is similar in shape to test_stream.py but stitches everything together.

- [ ] Run + commit `test(streaming): full proxy lifecycle e2e`.

---

## Task 13: Version bump + merge

- [ ] Bump version to `0.2.0-alpha.3` in `streamload/version.py`.

- [ ] Run full suite:

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest -q
```

- [ ] Manual smoke (real network — only if you have a valid SC catalog entry):

```bash
DATABASE_URL=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload \
  TMDB_API_KEY=$KEY venv/bin/python streamload.py --api &

# Register + refresh catalog (use admin)
curl -X POST localhost:8000/api/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"a","email":"a@x.com","password":"Hunter2!secret"}' -c /tmp/c.txt
curl -X POST localhost:8000/api/admin/catalog/refresh/trending-day -b /tmp/c.txt
sleep 30

# Pick a tmdb_id from the catalog and try to play
curl -X POST localhost:8000/api/play/<tmdb_id> -b /tmp/c.txt
# -> {session_id: "...", master_url: "/stream/.../master.m3u8", ...}

curl -i localhost:8000/stream/<session_id>/master.m3u8
# Should return rewritten m3u8 with /stream/... URLs
```

- [ ] Merge:

```bash
git checkout main
git merge --no-ff feat/v2-streaming-proxy-drm -m "Merge branch 'feat/v2-streaming-proxy-drm'

Plan 3 of Streamload v2: HLS streaming proxy with cache + DRM.

Includes:
* In-memory PlaybackSession registry with TTL eviction
* HLS master + media playlist URL rewriting
* Disk LRU + RAM ring buffer segment caches
* Async segment fetcher with cache hierarchy + DRM decrypt hook
* WebVTT + SRT-to-VTT subtitle conversion
* Quality auto-probe (populates catalog_sources.quality_max_height)
* POST /api/play/{tmdb_id} returns session + ranked Server N options
* /stream/{sid}/{master,video,seg,sub} proxy endpoints

Spec: §6.3 + §8
Plan: docs/superpowers/plans/2026-05-08-streamload-v2-plan-3-streaming-proxy-drm.md"

git push origin main
git tag -a v0.2.0-alpha.3 -m "Plan 3 complete"
git push origin v0.2.0-alpha.3
```

---

## Self-Review Checklist

- [ ] All 13 tasks completed
- [ ] `pytest -q` all green (Plan 1+2+3)
- [ ] `POST /api/play/{tmdb_id}` returns valid session
- [ ] `GET /stream/{sid}/master.m3u8` returns valid HLS with no upstream URLs leaked
- [ ] Segment proxy serves bytes (mocked or real)
- [ ] DRM decrypt path tested (mocked); existing `core/drm/` integration verified
- [ ] No `Co-Authored-By` trailers
- [ ] Version `0.2.0-alpha.3` tagged

---

## Open issues (post-Plan-3, deferred)

- Real-world DRM testing requires a valid Widevine CDM (existing v1 has it; production deployment will configure)
- Persistent quality_max_height + latency stats need warmup runs
- Plan 4 (frontend) consumes the `/api/play` + `/stream/...` endpoints
- Multi-mirror retry on segment failure is a Plan 5 polish item
