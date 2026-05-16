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


# ──────────────────────────────────────────────────────────────────────────
# Home "rows" — thin TMDB proxies returning MediaSummary-shaped JSON.
# Used by the client's PosterRow / BackdropRow components. Each row endpoint
# is independent so a slow / failing row doesn't block the whole page.
# Hard cap each response at 20 items; the client never paginates a row.
# ──────────────────────────────────────────────────────────────────────────

# Hardcoded cap to keep responses cheap and consistent — rows are visual
# strips, never paginated. Bump only if a design genuinely needs more.
_ROW_LIMIT = 20


class MediaSummaryResponse(BaseModel):
    """Mirrors ``streamload_client.MediaSummary`` 1:1.

    Kept inline here (rather than imported from a shared schema) because
    catalog rows are the only producer and the client model is the only
    consumer — a shared module would add ceremony for one type.
    """
    tmdb_id: int
    media_type: str
    title: str
    year: int | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None


def _to_summary(item: TmdbItem) -> MediaSummaryResponse:
    return MediaSummaryResponse(
        tmdb_id=item.tmdb_id,
        media_type=item.media_type,
        title=item.title,
        year=item.year,
        poster_url=item.poster_url,
        backdrop_url=item.backdrop_url,
    )


def _require_tmdb_key() -> str:
    api_key = os.environ.get("TMDB_API_KEY", "")
    if not api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "TMDB not configured")
    return api_key


def _validate_media_type(value: str, *, allow_all: bool = False) -> str:
    allowed = {"movie", "tv"} | ({"all"} if allow_all else set())
    if value not in allowed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"media_type must be one of {sorted(allowed)}",
        )
    return value


@router.get("/rows/trending", response_model=list[MediaSummaryResponse])
async def rows_trending(
    user: CurrentUser,
    period: str = "week",
    media_type: str = "all",
) -> list[MediaSummaryResponse]:
    """``period`` is ``day`` or ``week``; ``media_type`` is ``all``/``movie``/``tv``."""
    if period not in ("day", "week"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "period must be 'day' or 'week'")
    _validate_media_type(media_type, allow_all=True)
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        fn = tmdb.trending_day if period == "day" else tmdb.trending_week
        items = await fn(media_type=media_type)
    return [_to_summary(i) for i in items[:_ROW_LIMIT]]


@router.get("/rows/new-releases", response_model=list[MediaSummaryResponse])
async def rows_new_releases(
    user: CurrentUser,
    media_type: str,
) -> list[MediaSummaryResponse]:
    _validate_media_type(media_type)
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        items = await tmdb.new_releases(media_type=media_type)
    return [_to_summary(i) for i in items[:_ROW_LIMIT]]


@router.get("/rows/by-genre", response_model=list[MediaSummaryResponse])
async def rows_by_genre(
    user: CurrentUser,
    genre_ids: str,
    media_type: str,
    original_language: str | None = None,
) -> list[MediaSummaryResponse]:
    """``genre_ids`` is a comma-separated list of TMDB genre IDs (e.g. ``80,53``)."""
    _validate_media_type(media_type)
    try:
        ids = [int(g) for g in genre_ids.split(",") if g.strip()]
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "genre_ids must be a comma-separated list of integers",
        )
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "genre_ids required")
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        items = await tmdb.discover_by_genre(
            genre_ids=ids,
            media_type=media_type,
            original_language=original_language,
        )
    return [_to_summary(i) for i in items[:_ROW_LIMIT]]


@router.get("/rows/top-rated", response_model=list[MediaSummaryResponse])
async def rows_top_rated(
    user: CurrentUser,
    media_type: str,
) -> list[MediaSummaryResponse]:
    _validate_media_type(media_type)
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        if media_type == "movie":
            items = await tmdb.top_rated_movies()
        else:
            items = await tmdb.top_rated_tv()
    return [_to_summary(i) for i in items[:_ROW_LIMIT]]


@router.get("/{tmdb_id}/similar", response_model=list[MediaSummaryResponse])
async def get_item_similar(
    tmdb_id: int,
    user: CurrentUser,
    media_type: str,
) -> list[MediaSummaryResponse]:
    _validate_media_type(media_type)
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        try:
            items = await tmdb.similar(tmdb_id, media_type=media_type)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            log.warning("TMDB similar %s/%s error: %s", media_type, tmdb_id, e)
            return []
    return [_to_summary(i) for i in items[:_ROW_LIMIT]]


@router.get("/{tmdb_id}/recommendations", response_model=list[MediaSummaryResponse])
async def get_item_recommendations(
    tmdb_id: int,
    user: CurrentUser,
    media_type: str,
) -> list[MediaSummaryResponse]:
    _validate_media_type(media_type)
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        try:
            items = await tmdb.recommendations(tmdb_id, media_type=media_type)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            log.warning(
                "TMDB recommendations %s/%s error: %s",
                media_type,
                tmdb_id,
                e,
            )
            return []
    return [_to_summary(i) for i in items[:_ROW_LIMIT]]


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
