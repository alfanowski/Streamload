"""Catalog ingestion orchestrator.

v3: TMDB-only ingestion, no services / reverse-lookup.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from streamload.catalog.ingest import ingest_collection
from streamload.catalog.tmdb import TmdbItem
from streamload.db import create_engine, create_session_factory
from streamload.db.models import CatalogItem, Collection, CollectionItem


@pytest_asyncio.fixture
async def db_session():
    url = os.environ.get(
        "DATABASE_URL_TEST",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test",
    )
    engine = create_engine(url)
    factory = create_session_factory(engine)
    async with factory() as s:
        for tbl in ("collection_items", "tv_episodes", "catalog_items", "collections"):
            await s.execute(text(f"TRUNCATE TABLE {tbl} CASCADE"))
        await s.commit()
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_persists_collection_items(db_session):
    items = [
        TmdbItem(tmdb_id=100, media_type="movie", title="Movie A", year=2024),
        TmdbItem(tmdb_id=200, media_type="movie", title="Movie B", year=2023),
    ]
    await ingest_collection(
        db_session,
        collection_id="trending-day",
        collection_title="Trending oggi",
        media_type=None,
        sort_order=10,
        refresh_ttl_hours=6,
        items=items,
    )
    items_db = (await db_session.execute(select(CatalogItem))).scalars().all()
    assert len(items_db) == 2

    coll_items = (await db_session.execute(select(CollectionItem))).scalars().all()
    assert {ci.tmdb_id for ci in coll_items} == {100, 200}


@pytest.mark.asyncio
async def test_ingest_creates_collection_row(db_session):
    items = [TmdbItem(tmdb_id=1, media_type="movie", title="X", year=2024)]
    await ingest_collection(
        db_session, collection_id="c1", collection_title="C1",
        media_type="movie", sort_order=1, refresh_ttl_hours=24,
        items=items,
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
            items=items,
        )
    coll_items = (await db_session.execute(select(CollectionItem))).scalars().all()
    assert {ci.tmdb_id for ci in coll_items} == {2}
