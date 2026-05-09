"""Catalog detail endpoint + admin refresh."""
from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel

from streamload.api.deps import AdminUser, CurrentUser, SessionDep
from streamload.catalog.collections import get_collection_def
from streamload.catalog.ingest import ingest_collection, ingest_single_title
from streamload.catalog.ranker import SourceMetrics, rank_sources
from streamload.catalog.service import CatalogService
from streamload.catalog.tmdb import TmdbClient, TmdbItem
from streamload.utils.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/catalog", tags=["catalog"])


class SourceResponse(BaseModel):
    label: str
    score: float


class CatalogItemResponse(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    original_title: str | None
    year: int | None
    poster_url: str | None
    backdrop_url: str | None
    overview: str | None
    rating: float | None
    runtime_minutes: int | None
    seasons_count: int | None
    genres: list[str]
    sources: list[SourceResponse]


async def _fetch_tmdb_item(
    client: TmdbClient, tmdb_id: int, media_type: Optional[str],
) -> Optional[TmdbItem]:
    """Try the requested media_type first, then the other (TMDB IDs are *not*
    unique across the movie/tv namespaces)."""
    order = ["movie", "tv"] if media_type != "tv" else ["tv", "movie"]
    for mt in order:
        try:
            return await client.get_movie(tmdb_id) if mt == "movie" else await client.get_tv(tmdb_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                log.warning("TMDB %s/%s error: %s", mt, tmdb_id, e)
            continue
        except Exception:
            log.warning("TMDB lookup failed for %s/%s", mt, tmdb_id, exc_info=True)
            continue
    return None


def _ranked_sources(item) -> list[SourceResponse]:
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
    return [SourceResponse(label=r.label, score=r.score) for r in ranked]


@router.get("/{tmdb_id}", response_model=CatalogItemResponse)
async def get_item(
    tmdb_id: int,
    db: SessionDep,
    user: CurrentUser,
    media_type: Optional[str] = None,
) -> CatalogItemResponse:
    svc = CatalogService(db)
    item = await svc.get_item(tmdb_id)

    if item is None:
        # Lazy-ingest: not in catalog yet — fetch from TMDB + reverse-lookup,
        # persist, then re-read. For TV series, also pulls every season's
        # episode list into tv_episodes.
        api_key = os.environ.get("TMDB_API_KEY", "")
        if not api_key:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "TMDB key missing on server")
        async with httpx.AsyncClient(timeout=15) as http:
            tmdb = TmdbClient(api_key=api_key, http=http)
            tmdb_item = await _fetch_tmdb_item(tmdb, tmdb_id, media_type)
            if tmdb_item is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "title not found on TMDB")
            from streamload.services import ServiceRegistry, load_services
            from streamload.utils.http import HttpClient
            load_services()
            services = [cls(HttpClient()) for cls in ServiceRegistry.get_all()]
            await ingest_single_title(db, item=tmdb_item, services=services, tmdb=tmdb)
        item = await svc.get_item(tmdb_id)
        if item is None:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "ingest failed")
    return CatalogItemResponse(
        tmdb_id=item.tmdb_id,
        media_type=item.media_type,
        title=item.title,
        original_title=item.original_title,
        year=item.year,
        poster_url=item.poster_url,
        backdrop_url=item.backdrop_url,
        overview=item.overview,
        rating=float(item.rating) if item.rating is not None else None,
        runtime_minutes=item.runtime_minutes,
        seasons_count=item.seasons_count,
        genres=item.genres,
        sources=_ranked_sources(item),
    )


async def _refresh_one(collection_id: str) -> None:
    """Refresh a single collection. Creates its own DB session."""
    cdef = get_collection_def(collection_id)
    if cdef is None:
        return
    api_key = os.environ.get("TMDB_API_KEY", "")
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        items = await cdef.fetch(tmdb)

    from streamload.services import ServiceRegistry, load_services
    from streamload.utils.http import HttpClient
    load_services()
    services = [cls(HttpClient()) for cls in ServiceRegistry.get_all()]

    from streamload.db.session import _session_factory
    if _session_factory is None:
        log.error("DB factory not initialized; cannot refresh %s", collection_id)
        return
    async with _session_factory() as db:
        await ingest_collection(
            db, collection_id=cdef.id, collection_title=cdef.title,
            media_type=cdef.media_type, sort_order=cdef.sort_order,
            refresh_ttl_hours=cdef.refresh_ttl_hours,
            items=items, services=services,
        )


admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.post("/catalog/refresh/{collection_id}", status_code=202)
async def admin_refresh(
    collection_id: str, db: SessionDep, user: AdminUser,
    background: BackgroundTasks,
) -> dict[str, str]:
    cdef = get_collection_def(collection_id)
    if cdef is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown collection")
    background.add_task(_refresh_one, collection_id)
    return {"status": "scheduled", "collection_id": collection_id}
