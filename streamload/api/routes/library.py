"""Library: paginated catalog browse."""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import CatalogItem

router = APIRouter(prefix="/library", tags=["library"])


class LibraryItem(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    year: int | None
    poster_url: str | None


class LibraryPage(BaseModel):
    items: list[LibraryItem]
    total: int
    page: int
    per_page: int


@router.get("", response_model=LibraryPage)
async def library(
    user: CurrentUser,
    db: SessionDep,
    media_type: str | None = Query(default=None, pattern=r"^(movie|tv)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=24, ge=1, le=100),
) -> LibraryPage:
    base = select(CatalogItem)
    if media_type:
        base = base.where(CatalogItem.media_type == media_type)

    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    rows = (await db.execute(
        base
        .order_by(CatalogItem.year.desc().nulls_last(), CatalogItem.title)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()

    return LibraryPage(
        items=[
            LibraryItem(
                tmdb_id=r.tmdb_id, media_type=r.media_type,
                title=r.title, year=r.year, poster_url=r.poster_url,
            )
            for r in rows
        ],
        total=total, page=page, per_page=per_page,
    )
