"""Playback session endpoint."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import CurrentUser, SessionDep
from streamload.catalog.ranker import SourceMetrics, rank_sources
from streamload.catalog.service import CatalogService
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
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"service {short_name!r} not registered",
        )
    return cls(HttpClient())


@router.post("/{tmdb_id}", response_model=PlaybackResponse)
async def start_playback(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
    server: str | None = Query(default=None),
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
        )
        for s in item.sources
    ]
    ranked = rank_sources(metrics, user_audio_pref="ita", user_subs_pref="ita")

    chosen = ranked[0]
    if server:
        for r in ranked:
            if r.label == server:
                chosen = r
                break

    service = _get_service(chosen.metrics.service_short_name)
    sess = await build_playback_session(
        user_id=user.id,
        tmdb_id=tmdb_id,
        service=service,
        media_id=chosen.metrics.service_media_id,
        media_url=chosen.metrics.service_url,
    )
    return PlaybackResponse(
        session_id=str(sess.id),
        master_url=f"/stream/{sess.id}/master.m3u8",
        current_server=chosen.label,
        available_servers=[
            ServerOption(label=r.label, score=r.score) for r in ranked
        ],
    )
