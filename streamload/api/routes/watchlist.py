"""Watchlist endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import CatalogItem, Watchlist

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistItem(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    poster_url: str | None


@router.get("", response_model=list[WatchlistItem])
async def list_watchlist(user: CurrentUser, db: SessionDep) -> list[WatchlistItem]:
    stmt = (
        select(CatalogItem)
        .join(
            Watchlist,
            (Watchlist.tmdb_id == CatalogItem.tmdb_id)
            & (Watchlist.media_type == CatalogItem.media_type),
        )
        .where(Watchlist.user_id == user.id)
        .order_by(Watchlist.added_at.desc())
    )
    items = (await db.execute(stmt)).scalars().all()
    return [
        WatchlistItem(
            tmdb_id=i.tmdb_id, media_type=i.media_type,
            title=i.title, poster_url=i.poster_url,
        )
        for i in items
    ]


@router.post("/{tmdb_id}", status_code=201)
async def add_to_watchlist(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
    media_type: str = Query(..., pattern="^(movie|tv)$"),
) -> dict[str, str]:
    stmt = insert(Watchlist).values(
        user_id=user.id, tmdb_id=tmdb_id, media_type=media_type,
    ).on_conflict_do_nothing()
    await db.execute(stmt)
    await db.commit()
    return {"status": "added"}


@router.delete("/{tmdb_id}", status_code=204)
async def remove_from_watchlist(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
    media_type: str = Query(..., pattern="^(movie|tv)$"),
) -> None:
    await db.execute(
        delete(Watchlist)
        .where(Watchlist.user_id == user.id)
        .where(Watchlist.tmdb_id == tmdb_id)
        .where(Watchlist.media_type == media_type)
    )
    await db.commit()
