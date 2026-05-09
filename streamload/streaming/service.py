"""Playback orchestrator: from canonical title → registered PlaybackSession."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from streamload.models.media import MediaEntry, MediaType
from streamload.utils.logger import get_logger

from .sessions import PlaybackSession, registry

log = get_logger(__name__)


def _build_media_entry(*, service: Any, media_id: str, media_url: str) -> MediaEntry:
    """Reconstruct the v1 MediaEntry that service.get_streams() expects.

    Catalog sources persist (service_short_name, service_media_id, service_url)
    but the v1 service plugins want a structured MediaEntry. We synthesize one
    from the persisted URL — title/genre/image are not required by get_streams.
    """
    return MediaEntry(
        id=media_id,
        title="",  # not consulted by get_streams
        type=MediaType.FILM,  # placeholder; type is not consulted by get_streams
        url=media_url,
        service=getattr(service, "short_name", ""),
    )


async def build_playback_session(
    *,
    user_id: uuid.UUID,
    tmdb_id: int,
    service: Any,
    media_id: str,
    media_url: str,
    episode_id: Optional[str] = None,
) -> PlaybackSession:
    """Resolve the upstream HLS bundle and register a playback session."""
    entry = _build_media_entry(service=service, media_id=media_id, media_url=media_url)
    if hasattr(service, "get_streams_async"):
        bundle = await service.get_streams_async(entry)
    else:
        import asyncio
        bundle = await asyncio.to_thread(service.get_streams, entry)

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
    log.info(
        "Created playback session %s (tmdb=%s service=%s drm=%s)",
        sess.id, tmdb_id, service.short_name, sess.is_drm,
    )
    return sess
