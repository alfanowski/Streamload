"""TV episodes endpoint — list seasons + episodes for a title.

Episodes live in the ``tv_episodes`` table. They're normally populated when a
title is first opened (lazy-ingest in the catalog route), but a series that
entered the catalog as metadata-only (e.g. ingested as part of a Home row, or
a show with many seasons whose first ingest was skipped because the catalog
row already existed) would have NO episodes — the list came back empty (the
operator saw this on The Simpsons). So this endpoint is self-sufficient: if the
DB has no episodes for the title, it pulls them from TMDB on demand (seasons
fetched concurrently) and caches them, then returns.
"""
from __future__ import annotations

import os

import httpx
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import CurrentUser, SessionDep
from streamload.catalog.ingest import ingest_single_title
from streamload.catalog.tmdb import TmdbClient
from streamload.db.models import TvEpisode
from streamload.utils.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/title", tags=["episodes"])


class EpisodeOut(BaseModel):
    episode_number: int
    title: str | None = None
    overview: str | None = None
    runtime_minutes: int | None = None
    still_url: str | None = None
    air_date: str | None = None


class SeasonOut(BaseModel):
    season_number: int
    episodes: list[EpisodeOut]


class EpisodesResponse(BaseModel):
    seasons: list[SeasonOut]


async def _episode_rows(db, tmdb_id: int):
    return (await db.execute(
        select(TvEpisode)
        .where(TvEpisode.tmdb_id == tmdb_id, TvEpisode.media_type == "tv")
        .order_by(TvEpisode.season_number, TvEpisode.episode_number)
    )).scalars().all()


async def _lazy_ingest_episodes(db, tmdb_id: int) -> None:
    """Pull a TV title (metadata + every season's episodes) from TMDB when its
    episodes are missing from the DB. Reuses ``ingest_single_title`` so the
    catalog row is upserted first (the tv_episodes FK requires it) and the
    seasons are fetched concurrently."""
    api_key = os.environ.get("TMDB_API_KEY", "")
    if not api_key:
        return
    async with httpx.AsyncClient(timeout=20) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        try:
            tv_item = await tmdb.get_tv(tmdb_id)
        except Exception:
            log.warning("TMDB tv detail failed for tmdb=%s", tmdb_id,
                        exc_info=True)
            return
        if (tv_item.seasons_count or 0) <= 0:
            return
        try:
            await ingest_single_title(db, item=tv_item, tmdb=tmdb)
        except Exception:
            await db.rollback()
            log.warning("Lazy episode ingestion failed for tmdb=%s", tmdb_id,
                        exc_info=True)


@router.get("/{tmdb_id}/episodes", response_model=EpisodesResponse)
async def list_episodes(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
) -> EpisodesResponse:
    """Return all seasons + episodes for a TV title.

    Reads from the ``tv_episodes`` table; if it's empty for this title, it
    lazily ingests every season from TMDB (concurrently), then re-reads.
    """
    rows = await _episode_rows(db, tmdb_id)
    if not rows:
        await _lazy_ingest_episodes(db, tmdb_id)
        rows = await _episode_rows(db, tmdb_id)
    if not rows:
        return EpisodesResponse(seasons=[])

    seasons_map: dict[int, list[EpisodeOut]] = {}
    for ep in rows:
        ep_out = EpisodeOut(
            episode_number=ep.episode_number,
            title=ep.title,
            overview=ep.overview,
            runtime_minutes=ep.runtime_minutes,
            still_url=ep.still_url,
            air_date=ep.air_date.isoformat() if ep.air_date else None,
        )
        seasons_map.setdefault(ep.season_number, []).append(ep_out)

    seasons = [
        SeasonOut(season_number=sn, episodes=eps)
        for sn, eps in sorted(seasons_map.items())
    ]
    return EpisodesResponse(seasons=seasons)
