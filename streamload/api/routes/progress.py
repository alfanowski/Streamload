"""Watch progress endpoints."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import CatalogItem, WatchProgress

router = APIRouter(tags=["progress"])

WATCHED_THRESHOLD = 0.90


class PostProgressRequest(BaseModel):
    tmdb_id: int
    media_type: str = Field(pattern="^(movie|tv)$")
    season_number: int | None = None
    episode_number: int | None = None
    position_seconds: int = Field(ge=0)
    duration_seconds: int = Field(ge=1)
    source: str | None = None


class ProgressItem(BaseModel):
    tmdb_id: int
    media_type: str
    season_number: int | None
    episode_number: int | None
    position_seconds: int
    duration_seconds: int
    title: str
    poster_url: str | None


class ContinueWatchingResponse(BaseModel):
    items: list[ProgressItem]


@router.post("/progress")
async def post_progress(payload: PostProgressRequest, user: CurrentUser, db: SessionDep) -> dict[str, str]:
    completed = (payload.position_seconds / payload.duration_seconds) >= WATCHED_THRESHOLD
    stmt = insert(WatchProgress).values(
        user_id=user.id,
        tmdb_id=payload.tmdb_id,
        media_type=payload.media_type,
        season_number=payload.season_number or 0,
        episode_number=payload.episode_number or 0,
        position_seconds=payload.position_seconds,
        duration_seconds=payload.duration_seconds,
        completed=completed,
        last_source=payload.source,
        updated_at=datetime.now(UTC),
    ).on_conflict_do_update(
        index_elements=["user_id", "tmdb_id", "media_type", "season_number", "episode_number"],
        set_={
            "position_seconds": payload.position_seconds,
            "duration_seconds": payload.duration_seconds,
            "completed": completed,
            "last_source": payload.source,
            "updated_at": datetime.now(UTC),
        },
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok", "completed": str(completed).lower()}


@router.get("/progress/continue-watching", response_model=ContinueWatchingResponse)
async def continue_watching(user: CurrentUser, db: SessionDep) -> ContinueWatchingResponse:
    stmt = (
        select(WatchProgress, CatalogItem)
        .join(
            CatalogItem,
            (CatalogItem.tmdb_id == WatchProgress.tmdb_id)
            & (CatalogItem.media_type == WatchProgress.media_type),
        )
        .where(WatchProgress.user_id == user.id)
        .where(WatchProgress.completed.is_(False))
        .order_by(WatchProgress.updated_at.desc())
        .limit(20)
    )
    rows = (await db.execute(stmt)).all()
    return ContinueWatchingResponse(items=[
        ProgressItem(
            tmdb_id=p.tmdb_id,
            media_type=p.media_type,
            season_number=p.season_number if p.season_number else None,
            episode_number=p.episode_number if p.episode_number else None,
            position_seconds=p.position_seconds,
            duration_seconds=p.duration_seconds,
            title=item.title,
            poster_url=item.poster_url,
        ) for p, item in rows
    ])
