"""Catalog detail endpoint.

v3: pure metadata mirror. Lazy-ingest pulls from TMDB when the title isn't
yet cached; sources are never resolved server-side and are always returned
as an empty list. The client resolves sources locally via its plugin runtime.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from streamload.api.deps import CurrentUser, SessionDep
from streamload.catalog.ingest import ingest_single_title
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
    sources: list[SourceResponse]   # always [] in v3 server response


async def _fetch_tmdb_item(
    client: TmdbClient, tmdb_id: int, media_type: Optional[str],
) -> Optional[TmdbItem]:
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


class VideoResponse(BaseModel):
    """Subset of TMDB ``/videos`` results — only fields the client uses."""
    key: str          # YouTube video id
    site: str         # always "YouTube" (filtered)
    type: str         # "Trailer" / "Teaser" / "Clip" / ...
    official: bool
    name: str | None = None


@router.get("/{tmdb_id}/videos", response_model=list[VideoResponse])
async def get_item_videos(
    tmdb_id: int,
    user: CurrentUser,
    media_type: str,
) -> list[VideoResponse]:
    """Proxy TMDB ``/{movie|tv}/{id}/videos``, returning YouTube items only.

    The client's HeroTrailer feeds the first matching key into a YouTube
    IFrame Player. We keep TMDB credentials server-side; the client never
    sees the API key.
    """
    if media_type not in ("movie", "tv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "media_type must be 'movie' or 'tv'")
    api_key = os.environ.get("TMDB_API_KEY", "")
    if not api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "TMDB not configured")
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        try:
            results = await tmdb.get_videos(tmdb_id, media_type=media_type)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            log.warning("TMDB videos %s/%s error: %s", media_type, tmdb_id, e)
            return []
    return [
        VideoResponse(
            key=str(v.get("key") or ""),
            site=str(v.get("site") or ""),
            type=str(v.get("type") or ""),
            official=bool(v.get("official", False)),
            name=v.get("name"),
        )
        for v in results
        if v.get("site") == "YouTube" and v.get("key")
    ]


@router.get("/{tmdb_id}", response_model=CatalogItemResponse)
async def get_item(
    tmdb_id: int,
    db: SessionDep,
    user: CurrentUser,
    media_type: Optional[str] = None,
) -> CatalogItemResponse:
    svc = CatalogService(db)
    item = await svc.get_item(tmdb_id, media_type=media_type)

    if item is None:
        api_key = os.environ.get("TMDB_API_KEY", "")
        if not api_key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "title not found in catalog")
        async with httpx.AsyncClient(timeout=15) as http:
            tmdb = TmdbClient(api_key=api_key, http=http)
            tmdb_item = await _fetch_tmdb_item(tmdb, tmdb_id, media_type)
            if tmdb_item is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "title not found on TMDB")
            await ingest_single_title(db, item=tmdb_item, tmdb=tmdb)
        item = await svc.get_item(tmdb_id, media_type=tmdb_item.media_type)
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
        sources=[],
    )
