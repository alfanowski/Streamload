"""Playback orchestrator: from canonical title → registered PlaybackSession."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from streamload.models.media import Episode, MediaEntry, MediaType
from streamload.utils.logger import get_logger

from .sessions import PlaybackSession, registry

log = get_logger(__name__)


def _build_media_entry(
    *, service: Any, media_id: str, media_url: str, is_tv: bool = False,
) -> MediaEntry:
    """Reconstruct the v1 MediaEntry that service.get_streams() expects."""
    return MediaEntry(
        id=media_id,
        title="",
        type=MediaType.SERIE if is_tv else MediaType.FILM,
        url=media_url,
        service=getattr(service, "short_name", ""),
    )


async def _resolve_tv_episode(
    *, service: Any, entry: MediaEntry, season_number: int, episode_number: int,
) -> Episode | None:
    """Walk the service's seasons + episodes to find the target episode."""
    seasons = await asyncio.to_thread(service.get_seasons, entry)
    target_season = next((s for s in seasons if s.number == season_number), None)
    if target_season is None:
        log.warning("season %s not found for service=%s tmdb=%s",
                    season_number, service.short_name, entry.id)
        return None
    episodes = await asyncio.to_thread(service.get_episodes, target_season)
    target = next((e for e in episodes if e.number == episode_number), None)
    if target is None:
        log.warning("episode %s/%s not found for service=%s tmdb=%s",
                    season_number, episode_number, service.short_name, entry.id)
    return target


async def build_playback_session(
    *,
    user_id: uuid.UUID,
    tmdb_id: int,
    service: Any,
    media_id: str,
    media_url: str,
    is_tv: bool = False,
    season_number: Optional[int] = None,
    episode_number: Optional[int] = None,
) -> PlaybackSession:
    """Resolve the upstream HLS bundle and register a playback session.

    For movies, calls service.get_streams(MediaEntry).
    For TV with season/episode, walks get_seasons → get_episodes to find the
    matching Episode and passes that to get_streams.
    """
    entry = _build_media_entry(service=service, media_id=media_id, media_url=media_url, is_tv=is_tv)

    target: Any = entry
    if is_tv and season_number is not None and episode_number is not None:
        ep = await _resolve_tv_episode(
            service=service, entry=entry,
            season_number=season_number, episode_number=episode_number,
        )
        if ep is None:
            from streamload.core.exceptions import ServiceError
            raise ServiceError(
                f"[{service.short_name}] episode S{season_number}E{episode_number} not found"
            )
        target = ep

    if hasattr(service, "get_streams_async"):
        bundle = await service.get_streams_async(target)
    else:
        bundle = await asyncio.to_thread(service.get_streams, target)

    sess = PlaybackSession.create(
        user_id=user_id,
        tmdb_id=tmdb_id,
        media_type="tv" if is_tv else "movie",
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
