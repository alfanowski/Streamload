import os
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text

from streamload.catalog.service import CatalogService
from streamload.db import create_engine, create_session_factory
from streamload.db.models import (
    CatalogItem, CatalogSource, Collection, CollectionItem,
)


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


@pytest_asyncio.fixture
async def seeded(db_session):
    db_session.add_all([
        Collection(id="c1", title="C1", sort_order=1, refresh_ttl_hours=24,
                   last_refreshed_at=datetime.now(UTC)),
        CatalogItem(tmdb_id=1, media_type="movie", title="A", year=2024),
        CatalogItem(tmdb_id=2, media_type="movie", title="B", year=2024),
        CatalogSource(tmdb_id=1, media_type="movie", service_short_name="sc", service_url="https://sc/1", service_media_id="1"),
        CatalogSource(tmdb_id=1, media_type="movie", service_short_name="rp", service_url="https://rp/1", service_media_id="1"),
        CollectionItem(collection_id="c1", tmdb_id=1, media_type="movie", position=0),
        CollectionItem(collection_id="c1", tmdb_id=2, media_type="movie", position=1),
    ])
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_item_returns_with_sources(db_session, seeded):
    s = CatalogService(db_session)
    item = await s.get_item(1)
    assert item is not None
    assert item.title == "A"
    assert len(item.sources) == 2


@pytest.mark.asyncio
async def test_get_item_unknown_returns_none(db_session, seeded):
    s = CatalogService(db_session)
    assert await s.get_item(9999) is None


@pytest.mark.asyncio
async def test_get_collection_returns_items_in_order(db_session, seeded):
    s = CatalogService(db_session)
    coll = await s.get_collection("c1")
    assert coll is not None
    ids = [i.tmdb_id for i in coll.items]
    assert ids == [1, 2]


@pytest.mark.asyncio
async def test_list_collections_sorted(db_session):
    db_session.add_all([
        Collection(id="b", title="B", sort_order=20, refresh_ttl_hours=24,
                   last_refreshed_at=datetime.now(UTC)),
        Collection(id="a", title="A", sort_order=10, refresh_ttl_hours=24,
                   last_refreshed_at=datetime.now(UTC)),
    ])
    await db_session.commit()
    s = CatalogService(db_session)
    out = await s.list_collections()
    assert [c.id for c in out] == ["a", "b"]
