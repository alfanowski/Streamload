"""Favorites endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from streamload.api.deps import CurrentUser, SessionDep
from streamload.api.telemetry import emit as emit_event
from streamload.db.models import CatalogItem, Favorite

router = APIRouter(prefix="/favorites", tags=["favorites"])


class FavoriteItem(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    poster_url: str | None


@router.get("", response_model=list[FavoriteItem])
async def list_favorites(user: CurrentUser, db: SessionDep) -> list[FavoriteItem]:
    stmt = (
        select(CatalogItem)
        .join(
            Favorite,
            (Favorite.tmdb_id == CatalogItem.tmdb_id)
            & (Favorite.media_type == CatalogItem.media_type),
        )
        .where(Favorite.user_id == user.id)
        .order_by(Favorite.added_at.desc())
    )
    items = (await db.execute(stmt)).scalars().all()
    return [
        FavoriteItem(
            tmdb_id=i.tmdb_id, media_type=i.media_type,
            title=i.title, poster_url=i.poster_url,
        )
        for i in items
    ]


@router.post("/{tmdb_id}", status_code=201)
async def add_favorite(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
    request: Request,
    media_type: str = Query(..., pattern="^(movie|tv)$"),
) -> dict[str, str]:
    stmt = insert(Favorite).values(
        user_id=user.id, tmdb_id=tmdb_id, media_type=media_type,
    ).on_conflict_do_nothing()
    await db.execute(stmt)
    await emit_event(db, request, user_id=user.id, event_type="favorite.add",
                     payload={"tmdb_id": tmdb_id, "media_type": media_type})
    await db.commit()
    return {"status": "added"}


@router.delete("/{tmdb_id}", status_code=204)
async def remove_favorite(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
    request: Request,
    media_type: str = Query(..., pattern="^(movie|tv)$"),
) -> None:
    await db.execute(
        delete(Favorite)
        .where(Favorite.user_id == user.id)
        .where(Favorite.tmdb_id == tmdb_id)
        .where(Favorite.media_type == media_type)
    )
    await emit_event(db, request, user_id=user.id, event_type="favorite.remove",
                     payload={"tmdb_id": tmdb_id, "media_type": media_type})
    await db.commit()
