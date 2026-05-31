"""Watch progress endpoints (v3 — no last_source field, watch_history side-effect)."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import CatalogItem, WatchHistory, WatchProgress

router = APIRouter(tags=["progress"])

WATCHED_THRESHOLD = 0.90


class PostProgressRequest(BaseModel):
    tmdb_id: int
    media_type: str = Field(pattern="^(movie|tv)$")
    season_number: int | None = None
    episode_number: int | None = None
    position_seconds: int = Field(ge=0)
    duration_seconds: int = Field(ge=1)


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

    # Was this row already completed before this update? Used to gate the
    # watch_history insertion (only on the false → true transition).
    prior = (await db.execute(
        select(WatchProgress.completed).where(
            WatchProgress.user_id == user.id,
            WatchProgress.tmdb_id == payload.tmdb_id,
            WatchProgress.media_type == payload.media_type,
            WatchProgress.season_number == (payload.season_number or 0),
            WatchProgress.episode_number == (payload.episode_number or 0),
        )
    )).scalar_one_or_none()
    was_completed = bool(prior) if prior is not None else False

    stmt = insert(WatchProgress).values(
        user_id=user.id,
        tmdb_id=payload.tmdb_id,
        media_type=payload.media_type,
        season_number=payload.season_number or 0,
        episode_number=payload.episode_number or 0,
        position_seconds=payload.position_seconds,
        duration_seconds=payload.duration_seconds,
        completed=completed,
        updated_at=datetime.now(UTC),
    ).on_conflict_do_update(
        index_elements=["user_id", "tmdb_id", "media_type", "season_number", "episode_number"],
        set_={
            "position_seconds": payload.position_seconds,
            "duration_seconds": payload.duration_seconds,
            "completed": completed,
            "updated_at": datetime.now(UTC),
        },
    )
    await db.execute(stmt)

    if completed and not was_completed:
        db.add(WatchHistory(
            user_id=user.id,
            tmdb_id=payload.tmdb_id,
            media_type=payload.media_type,
            season_number=payload.season_number or 0,
            episode_number=payload.episode_number or 0,
            completed_at=datetime.now(UTC),
        ))

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
        # Bound the scan: a heavy user can have hundreds of in-progress episode
        # rows (one per episode). We collapse to 20 TITLES below; 200 most-recent
        # rows is far more than enough to yield 20 distinct titles, while keeping
        # the query + JOIN from materialising the user's entire history in memory.
        .limit(200)
    )
    rows = (await db.execute(stmt)).all()

    # Collapse to ONE entry per title. A series has a separate WatchProgress row
    # per episode, so two in-progress episodes (e.g. just moved to the next one)
    # would otherwise show the show twice. We keep the most-recently-updated
    # episode (rows are already ordered updated_at desc).
    items: list[ProgressItem] = []
    seen: set[tuple[int, str]] = set()
    for p, item in rows:
        key = (p.tmdb_id, p.media_type)
        if key in seen:
            continue
        seen.add(key)
        items.append(ProgressItem(
            tmdb_id=p.tmdb_id,
            media_type=p.media_type,
            season_number=p.season_number if p.season_number else None,
            episode_number=p.episode_number if p.episode_number else None,
            position_seconds=p.position_seconds,
            duration_seconds=p.duration_seconds,
            title=item.title,
            poster_url=item.poster_url,
        ))
        if len(items) >= 20:
            break
    return ContinueWatchingResponse(items=items)


class ResumeResponse(BaseModel):
    position_seconds: int
    duration_seconds: int
    completed: bool


@router.get("/progress/{tmdb_id}", response_model=None)
async def get_progress(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
    media_type: str = Query("movie", pattern="^(movie|tv)$"),
    season_number: int | None = None,
    episode_number: int | None = None,
) -> ResumeResponse | Response:
    """Saved position for ONE exact title/episode — the client calls this on
    play to resume from where the user left off. Server-side so progress
    follows the user across devices. 204 when there's nothing saved.

    (Defined after /progress/continue-watching; the int path converter means
    the literal "continue-watching" never matches this route.)
    """
    row = (await db.execute(
        select(WatchProgress).where(
            WatchProgress.user_id == user.id,
            WatchProgress.tmdb_id == tmdb_id,
            WatchProgress.media_type == media_type,
            WatchProgress.season_number == (season_number or 0),
            WatchProgress.episode_number == (episode_number or 0),
        )
    )).scalar_one_or_none()
    if row is None:
        return Response(status_code=204)
    return ResumeResponse(
        position_seconds=row.position_seconds,
        duration_seconds=row.duration_seconds,
        completed=row.completed,
    )


@router.delete("/progress/continue-watching/{tmdb_id}")
async def remove_continue_watching(
    tmdb_id: int,
    media_type: str = Query(..., pattern="^(movie|tv)$"),
    user: CurrentUser,
    db: SessionDep,
) -> dict[str, str]:
    """Remove a title from the user's "Continua a guardare" row — deletes every
    episode's progress for that title (the long-press "Rimuovi dalla riga")."""
    await db.execute(
        delete(WatchProgress).where(
            WatchProgress.user_id == user.id,
            WatchProgress.tmdb_id == tmdb_id,
            WatchProgress.media_type == media_type,
        )
    )
    await db.commit()
    return {"status": "ok"}


class EpisodeProgressItem(BaseModel):
    season_number: int
    episode_number: int
    position_seconds: int
    duration_seconds: int
    completed: bool


class TitleProgressResponse(BaseModel):
    items: list[EpisodeProgressItem]


@router.get("/progress/title/{tmdb_id}", response_model=TitleProgressResponse)
async def title_progress(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
    media_type: str = Query("tv", pattern="^(movie|tv)$"),
) -> TitleProgressResponse:
    """EVERY saved episode's progress for a title — drives the title page's
    per-episode watch bars + "already watched" ticks (the platform's memory of
    what you've seen). Movies report a single (0,0) entry."""
    rows = (await db.execute(
        select(WatchProgress).where(
            WatchProgress.user_id == user.id,
            WatchProgress.tmdb_id == tmdb_id,
            WatchProgress.media_type == media_type,
        )
    )).scalars().all()
    return TitleProgressResponse(items=[
        EpisodeProgressItem(
            season_number=r.season_number,
            episode_number=r.episode_number,
            position_seconds=r.position_seconds,
            duration_seconds=r.duration_seconds,
            completed=r.completed,
        ) for r in rows
    ])
