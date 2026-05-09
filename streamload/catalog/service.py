"""Catalog facade — read-side API for routes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db.models import (
    CatalogItem,
    Collection,
    CollectionItem,
)


@dataclass
class CollectionWithItems:
    id: str
    title: str
    sort_order: int
    items: list[CatalogItem]


class CatalogService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_item(self, tmdb_id: int, media_type: Optional[str] = None) -> Optional[CatalogItem]:
        stmt = (
            select(CatalogItem)
            .where(CatalogItem.tmdb_id == tmdb_id)
        )
        if media_type is not None:
            stmt = stmt.where(CatalogItem.media_type == media_type)
        result = await self._db.execute(stmt)
        # If no media_type filter is given and both rows exist, return either
        # (caller should pass media_type to disambiguate). The migration
        # backfill ensures any legacy queries land on a deterministic row.
        return result.scalars().first()

    async def list_collections(self) -> list[Collection]:
        stmt = select(Collection).order_by(Collection.sort_order)
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_collection(self, collection_id: str) -> Optional[CollectionWithItems]:
        coll = (await self._db.execute(
            select(Collection).where(Collection.id == collection_id)
        )).scalar_one_or_none()
        if coll is None:
            return None
        items_stmt = (
            select(CatalogItem)
            .join(
                CollectionItem,
                (CollectionItem.tmdb_id == CatalogItem.tmdb_id)
                & (CollectionItem.media_type == CatalogItem.media_type),
            )
            .where(CollectionItem.collection_id == collection_id)
            .order_by(CollectionItem.position)
        )
        items = list((await self._db.execute(items_stmt)).scalars().all())
        return CollectionWithItems(
            id=coll.id, title=coll.title, sort_order=coll.sort_order, items=items,
        )
