"""Catalog ingestion orchestrator.

Verifies that for a TMDB collection result, services are queried in
parallel and matching results are persisted as catalog_sources.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from streamload.catalog.ingest import ingest_collection
from streamload.catalog.tmdb import TmdbItem
from streamload.db import create_engine, create_session_factory
from streamload.db.models import CatalogItem, CatalogSource, Collection, CollectionItem
from streamload.models.media import MediaEntry, MediaType


@pytest_asyncio.fixture
async def db_session():
    url = os.environ.get(
        "DATABASE_URL_TEST",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test",
    )
    engine = create_engine(url)
    factory = create_session_factory(engine)
    async with factory() as s:
        for tbl in ("collection_items", "catalog_sources", "tv_episodes",
                    "catalog_items", "collections"):
            await s.execute(text(f"TRUNCATE TABLE {tbl} CASCADE"))
        await s.commit()
        yield s
    await engine.dispose()


def _fake_service(name: str, short: str, results: list[MediaEntry]):
    svc = MagicMock()
    svc.name = name
    svc.short_name = short
    svc.search_async = AsyncMock(return_value=results)
    return svc


@pytest.mark.asyncio
async def test_ingest_persists_collection_items(db_session):
    items = [
        TmdbItem(tmdb_id=100, media_type="movie", title="Movie A", year=2024),
        TmdbItem(tmdb_id=200, media_type="movie", title="Movie B", year=2023),
    ]
    services = [
        _fake_service("SC", "sc", [
            MediaEntry(id="sc1", title="Movie A", type=MediaType.FILM, url="https://sc/a", service="sc", year=2024),
        ]),
        _fake_service("AU", "au", []),
    ]
    await ingest_collection(
        db_session,
        collection_id="trending-day",
        collection_title="Trending oggi",
        media_type=None,
        sort_order=10,
        refresh_ttl_hours=6,
        items=items,
        services=services,
    )
    items_db = (await db_session.execute(select(CatalogItem))).scalars().all()
    assert len(items_db) == 2

    sources = (await db_session.execute(select(CatalogSource))).scalars().all()
    # Only Movie A was matched by SC
    assert len(sources) == 1
    assert sources[0].tmdb_id == 100
    assert sources[0].service_short_name == "sc"

    coll_items = (await db_session.execute(select(CollectionItem))).scalars().all()
    assert {ci.tmdb_id for ci in coll_items} == {100, 200}


@pytest.mark.asyncio
async def test_ingest_creates_collection_row(db_session):
    items = [TmdbItem(tmdb_id=1, media_type="movie", title="X", year=2024)]
    await ingest_collection(
        db_session, collection_id="c1", collection_title="C1",
        media_type="movie", sort_order=1, refresh_ttl_hours=24,
        items=items, services=[],
    )
    coll = (await db_session.execute(select(Collection).where(Collection.id == "c1"))).scalar_one()
    assert coll.title == "C1"
    assert coll.last_refreshed_at is not None


@pytest.mark.asyncio
async def test_ingest_replaces_collection_items_on_refresh(db_session):
    items_v1 = [TmdbItem(tmdb_id=1, media_type="movie", title="X", year=2024)]
    items_v2 = [TmdbItem(tmdb_id=2, media_type="movie", title="Y", year=2024)]
    for items in (items_v1, items_v2):
        await ingest_collection(
            db_session, collection_id="c1", collection_title="C1",
            media_type="movie", sort_order=1, refresh_ttl_hours=24,
            items=items, services=[],
        )
    coll_items = (await db_session.execute(select(CollectionItem))).scalars().all()
    assert {ci.tmdb_id for ci in coll_items} == {2}
