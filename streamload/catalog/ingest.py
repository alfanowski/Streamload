"""Orchestrator: TMDB items -> reverse lookup -> persist catalog state."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db.models import (
    CatalogItem,
    CatalogSource,
    Collection,
    CollectionItem,
)
from streamload.utils.logger import get_logger

from .match import best_match
from .tmdb import TmdbItem

log = get_logger(__name__)

REVERSE_LOOKUP_CONCURRENCY = 8


async def _upsert_catalog_item(db: AsyncSession, item: TmdbItem) -> None:
    stmt = insert(CatalogItem).values(
        tmdb_id=item.tmdb_id,
        media_type=item.media_type,
        title=item.title,
        original_title=item.original_title,
        year=item.year,
        poster_url=item.poster_url,
        backdrop_url=item.backdrop_url,
        overview=item.overview,
        rating=item.rating,
        runtime_minutes=item.runtime_minutes,
        seasons_count=item.seasons_count,
        genres=item.genres,
        metadata_fetched_at=datetime.now(UTC),
    ).on_conflict_do_update(
        index_elements=["tmdb_id"],
        set_={
            "title": item.title,
            "original_title": item.original_title,
            "year": item.year,
            "poster_url": item.poster_url,
            "backdrop_url": item.backdrop_url,
            "overview": item.overview,
            "rating": item.rating,
            "runtime_minutes": item.runtime_minutes,
            "seasons_count": item.seasons_count,
            "genres": item.genres,
            "metadata_fetched_at": datetime.now(UTC),
        },
    )
    await db.execute(stmt)


async def _resolve_sources_for_item(
    db: AsyncSession,
    item: TmdbItem,
    services: list[Any],
    sem: asyncio.Semaphore,
) -> int:
    """Search each service for *item.title*. Persist matched sources. Returns count matched."""
    matched = 0
    for svc in services:
        async with sem:
            try:
                results = await svc.search_async(item.title)
            except Exception:
                log.warning("Service %s search failed for %r", svc.short_name, item.title, exc_info=True)
                continue
        match = best_match(results, target_title=item.title, target_year=item.year)
        if match is None:
            continue
        # Upsert catalog_sources row
        stmt = insert(CatalogSource).values(
            tmdb_id=item.tmdb_id,
            service_short_name=svc.short_name,
            service_url=match.url,
            service_media_id=str(match.id),
            quality_max_height=None,
            languages_audio=[],
            languages_subs=[],
            last_verified_at=datetime.now(UTC),
        ).on_conflict_do_update(
            index_elements=["tmdb_id", "service_short_name"],
            set_={
                "service_url": match.url,
                "service_media_id": str(match.id),
                "last_verified_at": datetime.now(UTC),
            },
        )
        await db.execute(stmt)
        matched += 1
    return matched


async def ingest_collection(
    db: AsyncSession,
    *,
    collection_id: str,
    collection_title: str,
    media_type: Optional[str],
    sort_order: int,
    refresh_ttl_hours: int,
    items: list[TmdbItem],
    services: list[Any],
) -> None:
    """Full ingest cycle for a collection.

    1. Upsert collection row
    2. Upsert each catalog_item
    3. For each item: parallel reverse-lookup on services, persist sources
    4. Replace collection_items membership with the new ordering
    """
    log.info("Ingesting collection %s (%d items)", collection_id, len(items))

    # 1. Collection row
    coll_stmt = insert(Collection).values(
        id=collection_id, title=collection_title, media_type=media_type,
        sort_order=sort_order, refresh_ttl_hours=refresh_ttl_hours,
        last_refreshed_at=datetime.now(UTC),
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={
            "title": collection_title, "media_type": media_type,
            "sort_order": sort_order, "refresh_ttl_hours": refresh_ttl_hours,
            "last_refreshed_at": datetime.now(UTC),
        },
    )
    await db.execute(coll_stmt)

    # 2. Catalog items
    for it in items:
        await _upsert_catalog_item(db, it)

    # 3. Reverse-lookup sources in parallel
    sem = asyncio.Semaphore(REVERSE_LOOKUP_CONCURRENCY)
    await asyncio.gather(*[
        _resolve_sources_for_item(db, it, services, sem) for it in items
    ])

    # 4. Replace collection_items
    await db.execute(
        delete(CollectionItem).where(CollectionItem.collection_id == collection_id)
    )
    for pos, it in enumerate(items):
        db.add(CollectionItem(
            collection_id=collection_id, tmdb_id=it.tmdb_id, position=pos,
        ))

    await db.commit()
    log.info("Ingest complete for %s", collection_id)
