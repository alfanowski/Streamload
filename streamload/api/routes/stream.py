"""HLS proxy: master, media, segment, subtitle endpoints."""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Response, status

from streamload.streaming.disk_cache import SegmentCache
from streamload.streaming.fetcher import SegmentFetcher
from streamload.streaming.m3u8_rewrite import rewrite_master, rewrite_media
from streamload.streaming.ram_buffer import RamRingBuffer
from streamload.streaming.sessions import registry

router = APIRouter(prefix="/stream", tags=["stream"])

# ---------------------------------------------------------------------------
# Module-level singletons (lazy-init)
# ---------------------------------------------------------------------------

_disk_cache: Optional[SegmentCache] = None
_ram_buffers: dict[uuid.UUID, RamRingBuffer] = {}
_global_http: Optional[httpx.AsyncClient] = None


def _get_http() -> httpx.AsyncClient:
    """Module-level singleton httpx client (cleaned up at app shutdown)."""
    global _global_http
    if _global_http is None:
        _global_http = httpx.AsyncClient(timeout=30)
    return _global_http


async def shutdown_http() -> None:
    """Close the singleton client. Called from app lifespan."""
    global _global_http
    if _global_http is not None:
        await _global_http.aclose()
        _global_http = None


def _get_disk_cache() -> SegmentCache:
    global _disk_cache
    if _disk_cache is None:
        _disk_cache = SegmentCache(
            directory=str(Path("data/cache/segments")),
            size_limit_bytes=30 * 1024 * 1024 * 1024,
        )
    return _disk_cache


def _get_ram_buffer(session_id: uuid.UUID) -> RamRingBuffer:
    if session_id not in _ram_buffers:
        _ram_buffers[session_id] = RamRingBuffer(capacity=30)
    return _ram_buffers[session_id]


def seg_fetcher_for_session(session_id: uuid.UUID) -> SegmentFetcher:
    """Build (or reuse) a SegmentFetcher for the given session."""
    from streamload.streaming.drm import build_decryptor
    sess = registry.get(session_id)
    decryptor = None
    if sess is not None and sess.is_drm:
        decryptor = build_decryptor(keys=sess.drm_keys)
    return SegmentFetcher(
        http=_get_http(),
        ram=_get_ram_buffer(session_id),
        disk=_get_disk_cache(),
        decryptor=decryptor,
    )


# ---------------------------------------------------------------------------
# Upstream fetcher (mockable in tests)
# ---------------------------------------------------------------------------

async def _fetch_upstream_text(url: str, headers: dict[str, str]) -> str:
    http = _get_http()
    r = await http.get(url, headers=headers)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

async def _update_quality_if_needed(sess: object, upstream_text: str) -> None:
    """Persist quality_max_height to catalog_sources on first master fetch."""
    from streamload.streaming.quality_probe import max_height_from_master
    from streamload.db.session import _session_factory
    from streamload.db.models import CatalogSource
    from sqlalchemy import select, update

    height = max_height_from_master(upstream_text)
    if height is None or _session_factory is None:
        return
    try:
        async with _session_factory() as db:
            result = await db.execute(
                select(CatalogSource).where(
                    CatalogSource.tmdb_id == sess.tmdb_id,  # type: ignore[union-attr]
                    CatalogSource.media_type == sess.media_type,  # type: ignore[union-attr]
                    CatalogSource.service_short_name == sess.service_short_name,  # type: ignore[union-attr]
                    CatalogSource.quality_max_height.is_(None),
                )
            )
            source = result.scalar_one_or_none()
            if source is not None:
                source.quality_max_height = height
                await db.commit()
    except Exception:
        pass  # Quality probe is best-effort; never fail the proxy response


@router.get("/{session_id}/master.m3u8")
async def proxy_master(session_id: uuid.UUID) -> Response:
    sess = registry.get(session_id, touch=True)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session expired or unknown")
    upstream_text = await _fetch_upstream_text(
        sess.upstream_master_url, sess.upstream_headers
    )
    rewritten = rewrite_master(
        upstream_text,
        session_id=str(session_id),
        base_path=f"/stream/{session_id}",
    )
    # Best-effort quality probe — update catalog_sources if not yet set
    import asyncio
    asyncio.ensure_future(_update_quality_if_needed(sess, upstream_text))
    return Response(rewritten, media_type="application/x-mpegURL")


@router.get("/{session_id}/video/{rendition}.m3u8")
async def proxy_media_video(session_id: uuid.UUID, rendition: str) -> Response:
    sess = registry.get(session_id, touch=True)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session expired or unknown")
    master_text = await _fetch_upstream_text(
        sess.upstream_master_url, sess.upstream_headers
    )
    # Find the upstream URL for this rendition label
    upstream_rendition_url: Optional[str] = None
    lines = master_text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:") and i + 1 < len(lines):
            url = lines[i + 1].strip()
            if rendition in url:
                upstream_rendition_url = url
                break
    if upstream_rendition_url is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"rendition {rendition!r} not in master"
        )
    media_text = await _fetch_upstream_text(
        upstream_rendition_url, sess.upstream_headers
    )
    rewritten = rewrite_media(
        media_text,
        session_id=str(session_id),
        rendition=rendition,
        base_path=f"/stream/{session_id}",
    )
    return Response(rewritten, media_type="application/x-mpegURL")


@router.get("/{session_id}/audio/{lang}.m3u8")
async def proxy_media_audio(session_id: uuid.UUID, lang: str) -> Response:
    sess = registry.get(session_id, touch=True)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session expired or unknown")
    master_text = await _fetch_upstream_text(
        sess.upstream_master_url, sess.upstream_headers
    )
    audio_url: Optional[str] = None
    for line in master_text.split("\n"):
        if (
            line.startswith("#EXT-X-MEDIA:")
            and "TYPE=AUDIO" in line
            and f'LANGUAGE="{lang}"' in line
        ):
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                audio_url = m.group(1)
                break
    if audio_url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"audio {lang!r} not in master")
    media_text = await _fetch_upstream_text(audio_url, sess.upstream_headers)
    rewritten = rewrite_media(
        media_text,
        session_id=str(session_id),
        rendition=f"audio-{lang}",
        base_path=f"/stream/{session_id}",
    )
    return Response(rewritten, media_type="application/x-mpegURL")


def _find_rendition_url(master_text: str, rendition: str) -> Optional[str]:
    """Locate the upstream playlist URL for a given rendition label.

    Handles three cases:
      - video renditions: `audio="…"` STREAM-INF where the URI is on the
        following line and contains the rendition label;
      - audio renditions (label like `audio-ita`): `EXT-X-MEDIA:TYPE=AUDIO`
        with `LANGUAGE="ita"`, URI in attribute;
      - subtitle renditions are served by a dedicated endpoint.
    """
    if rendition.startswith("audio-"):
        target_lang = rendition[len("audio-"):]
        for line in master_text.split("\n"):
            if (
                line.startswith("#EXT-X-MEDIA:")
                and "TYPE=AUDIO" in line
                and f'LANGUAGE="{target_lang}"' in line
            ):
                m = re.search(r'URI="([^"]+)"', line)
                if m:
                    return m.group(1)
        return None
    # Video rendition — STREAM-INF + next-line URI.
    lines = master_text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:") and i + 1 < len(lines):
            url = lines[i + 1].strip()
            if rendition in url:
                return url
    return None


@router.get("/{session_id}/key/{rendition}")
async def proxy_aes_key(session_id: uuid.UUID, rendition: str) -> Response:
    """Proxy the upstream AES-128 key for HLS clear-key encryption."""
    from urllib.parse import urljoin

    sess = registry.get(session_id, touch=True)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session expired or unknown")

    master_text = await _fetch_upstream_text(
        sess.upstream_master_url, sess.upstream_headers,
    )
    rendition_url = _find_rendition_url(master_text, rendition)
    if rendition_url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rendition {rendition!r} not found")

    media_text = await _fetch_upstream_text(rendition_url, sess.upstream_headers)
    key_uri: Optional[str] = None
    for line in media_text.split("\n"):
        if line.startswith("#EXT-X-KEY:"):
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                key_uri = m.group(1)
                break
    if key_uri is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no AES-128 key in playlist")

    absolute_key_url = urljoin(rendition_url, key_uri)
    http = _get_http()
    r = await http.get(absolute_key_url, headers=sess.upstream_headers)
    r.raise_for_status()
    return Response(r.content, media_type="application/octet-stream")


@router.get("/{session_id}/seg/{rendition}/{n}.ts")
async def proxy_segment(session_id: uuid.UUID, rendition: str, n: int) -> Response:
    """Fetch segment N for the given rendition, with cache + DRM decrypt."""
    sess = registry.get(session_id, touch=True)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session expired or unknown")

    master_text = await _fetch_upstream_text(
        sess.upstream_master_url, sess.upstream_headers
    )
    rendition_url = _find_rendition_url(master_text, rendition)
    if rendition_url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rendition {rendition!r} not found")

    media_text = await _fetch_upstream_text(rendition_url, sess.upstream_headers)
    seg_urls = [
        ln.strip()
        for ln in media_text.split("\n")
        if ln.strip() and not ln.startswith("#")
    ]
    if n >= len(seg_urls):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"segment {n} out of range")

    upstream_seg = seg_urls[n]
    cache_key = f"{session_id}:{rendition}:{n}"
    fetcher = seg_fetcher_for_session(session_id)
    data = await fetcher.fetch(
        cache_key, upstream_url=upstream_seg, headers=sess.upstream_headers
    )
    return Response(data, media_type="video/mp2t")


@router.get("/{session_id}/sub/{lang}.vtt")
async def proxy_subtitle(session_id: uuid.UUID, lang: str) -> Response:
    """Proxy + convert subtitle stream to WebVTT."""
    sess = registry.get(session_id, touch=True)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session expired or unknown")

    master_text = await _fetch_upstream_text(
        sess.upstream_master_url, sess.upstream_headers
    )
    sub_url: Optional[str] = None
    for line in master_text.split("\n"):
        if (
            line.startswith("#EXT-X-MEDIA:")
            and "TYPE=SUBTITLES" in line
            and f'LANGUAGE="{lang}"' in line
        ):
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                sub_url = m.group(1)
                break
    if sub_url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"subtitle {lang!r} not in master")

    text = await _fetch_upstream_text(sub_url, sess.upstream_headers)
    from streamload.streaming.vtt import is_webvtt, srt_to_vtt
    if not is_webvtt(text):
        text = srt_to_vtt(text)
    return Response(text, media_type="text/vtt")
