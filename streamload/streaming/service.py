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
    log.info(
        "Created playback session %s (tmdb=%s service=%s drm=%s)",
        sess.id, tmdb_id, service.short_name, sess.is_drm,
    )
    return sess
