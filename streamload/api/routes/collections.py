"""Collection list + detail endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from streamload.api.deps import CurrentUser, SessionDep
from streamload.catalog.service import CatalogService

router = APIRouter(prefix="/collections", tags=["collections"])


class CatalogItemSummary(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    year: int | None
    poster_url: str | None


class CollectionSummary(BaseModel):
    id: str
    title: str
    sort_order: int
    media_type: str | None
    items: list[CatalogItemSummary]


class CollectionDetail(BaseModel):
    id: str
    title: str
    sort_order: int
    items: list[CatalogItemSummary]


@router.get("", response_model=list[CollectionSummary])
async def list_collections(db: SessionDep, user: CurrentUser) -> list[CollectionSummary]:
    """List collections with their items inlined.

    The home page consumes this single endpoint and renders a row per
    collection — it should not need to fan out to N detail calls. Per-row
    item count is intentionally bounded by the seed (defaults to ~20 items
    per collection).
    """
    svc = CatalogService(db)
    summaries = await svc.list_collections()
    out: list[CollectionSummary] = []
    for c in summaries:
        detail = await svc.get_collection(c.id)
        items = [] if detail is None else [
            CatalogItemSummary(
                tmdb_id=i.tmdb_id, media_type=i.media_type,
                title=i.title, year=i.year, poster_url=i.poster_url,
            ) for i in detail.items
        ]
        out.append(CollectionSummary(
            id=c.id, title=c.title, sort_order=c.sort_order,
            media_type=c.media_type, items=items,
        ))
    return out


@router.get("/{collection_id}", response_model=CollectionDetail)
async def get_collection(collection_id: str, db: SessionDep, user: CurrentUser) -> CollectionDetail:
    svc = CatalogService(db)
    coll = await svc.get_collection(collection_id)
    if coll is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "collection not found")
    return CollectionDetail(
        id=coll.id,
        title=coll.title,
        sort_order=coll.sort_order,
        items=[
            CatalogItemSummary(
                tmdb_id=i.tmdb_id, media_type=i.media_type,
                title=i.title, year=i.year, poster_url=i.poster_url,
            ) for i in coll.items
        ],
    )
