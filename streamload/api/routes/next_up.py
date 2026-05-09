"""Next-up endpoint: given (tmdb_id, season, episode), return the next episode."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import CatalogItem, TvEpisode

router = APIRouter(tags=["next-up"])


class NextEpisode(BaseModel):
    tmdb_id: int
    season_number: int
    episode_number: int
    title: str | None
    still_url: str | None


@router.get("/next-up/{tmdb_id}")
async def next_up(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
    response: Response,
    season: int = Query(..., ge=1),
    episode: int = Query(..., ge=1),
) -> NextEpisode | None:
    series = (await db.execute(
        select(CatalogItem).where(
            CatalogItem.tmdb_id == tmdb_id,
            CatalogItem.media_type == "tv",
        )
    )).scalar_one_or_none()
    if series is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "series not found")

    next_in_season = (await db.execute(
        select(TvEpisode)
        .where(
            TvEpisode.tmdb_id == tmdb_id,
            TvEpisode.media_type == "tv",
            TvEpisode.season_number == season,
            TvEpisode.episode_number > episode,
        )
        .order_by(TvEpisode.episode_number.asc())
        .limit(1)
    )).scalar_one_or_none()
    if next_in_season is not None:
        return NextEpisode(
            tmdb_id=tmdb_id,
            season_number=next_in_season.season_number,
            episode_number=next_in_season.episode_number,
            title=next_in_season.title,
            still_url=next_in_season.still_url,
        )

    first_of_next_season = (await db.execute(
        select(TvEpisode)
        .where(
            TvEpisode.tmdb_id == tmdb_id,
            TvEpisode.media_type == "tv",
            TvEpisode.season_number > season,
        )
        .order_by(TvEpisode.season_number.asc(), TvEpisode.episode_number.asc())
        .limit(1)
    )).scalar_one_or_none()
    if first_of_next_season is not None:
        return NextEpisode(
            tmdb_id=tmdb_id,
            season_number=first_of_next_season.season_number,
            episode_number=first_of_next_season.episode_number,
            title=first_of_next_season.title,
            still_url=first_of_next_season.still_url,
        )

    response.status_code = status.HTTP_204_NO_CONTENT
    return None
