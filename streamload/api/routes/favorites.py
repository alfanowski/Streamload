"""Favorites endpoints."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import CatalogItem, Favorite

router = APIRouter(prefix="/favorites", tags=["favorites"])


class FavoriteItem(BaseModel):
    tmdb_id: int
    title: str
    poster_url: str | None


@router.get("", response_model=list[FavoriteItem])
async def list_favorites(user: CurrentUser, db: SessionDep) -> list[FavoriteItem]:
    stmt = (
        select(CatalogItem)
        .join(Favorite, Favorite.tmdb_id == CatalogItem.tmdb_id)
        .where(Favorite.user_id == user.id)
        .order_by(Favorite.added_at.desc())
    )
    items = (await db.execute(stmt)).scalars().all()
    return [FavoriteItem(tmdb_id=i.tmdb_id, title=i.title, poster_url=i.poster_url) for i in items]


@router.post("/{tmdb_id}", status_code=201)
async def add_favorite(tmdb_id: int, user: CurrentUser, db: SessionDep) -> dict[str, str]:
    stmt = insert(Favorite).values(user_id=user.id, tmdb_id=tmdb_id).on_conflict_do_nothing()
    await db.execute(stmt)
    await db.commit()
    return {"status": "added"}


@router.delete("/{tmdb_id}", status_code=204)
async def remove_favorite(tmdb_id: int, user: CurrentUser, db: SessionDep) -> None:
    await db.execute(
        delete(Favorite).where(Favorite.user_id == user.id).where(Favorite.tmdb_id == tmdb_id)
    )
    await db.commit()
