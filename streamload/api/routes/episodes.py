"""TV episodes endpoint — list seasons + episodes for a title."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import TvEpisode

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


@router.get("/{tmdb_id}/episodes", response_model=EpisodesResponse)
async def list_episodes(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
) -> EpisodesResponse:
    """Return all seasons + episodes for a TV title, read from tv_episodes table."""
    rows = (await db.execute(
        select(TvEpisode)
        .where(TvEpisode.tmdb_id == tmdb_id, TvEpisode.media_type == "tv")
        .order_by(TvEpisode.season_number, TvEpisode.episode_number)
    )).scalars().all()

    if not rows:
        return EpisodesResponse(seasons=[])

    # Group by season number
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
