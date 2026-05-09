"""Catalog refresh worker logic (no scheduler loop)."""
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import text

from streamload.catalog.collections import CollectionDef
from streamload.catalog.tmdb import TmdbItem
from streamload.catalog.worker import refresh_due_collections
from streamload.db import create_engine, create_session_factory
from streamload.db.models import Collection


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
async def test_refresh_runs_collections_past_ttl(db_session):
    # Seed an old collection (last refreshed 2 days ago, ttl=24h -> due)
    old = datetime.now(UTC) - timedelta(hours=48)
    db_session.add(Collection(
        id="trending-day", title="X", sort_order=10,
        refresh_ttl_hours=24, last_refreshed_at=old,
    ))
    await db_session.commit()

    fake_tmdb = MagicMock()
    fake_tmdb.trending_day = AsyncMock(return_value=[
        TmdbItem(tmdb_id=1, media_type="movie", title="Y", year=2024),
    ])
    test_def = CollectionDef(
        id="trending-day", title="Trending oggi", media_type=None,
        sort_order=10, refresh_ttl_hours=24,
        fetch=lambda c: c.trending_day(),
    )
    refreshed = await refresh_due_collections(
        db_session, tmdb_client=fake_tmdb,
        collection_defs=[test_def],
    )
    assert refreshed == ["trending-day"]


@pytest.mark.asyncio
async def test_refresh_skips_recent_collections(db_session):
    # Refreshed 1h ago, ttl=24h -> NOT due
    recent = datetime.now(UTC) - timedelta(hours=1)
    db_session.add(Collection(
        id="trending-day", title="X", sort_order=10,
        refresh_ttl_hours=24, last_refreshed_at=recent,
    ))
    await db_session.commit()

    fake_tmdb = MagicMock()
    fake_tmdb.trending_day = AsyncMock(return_value=[])
    test_def = CollectionDef(
        id="trending-day", title="Trending oggi", media_type=None,
        sort_order=10, refresh_ttl_hours=24,
        fetch=lambda c: c.trending_day(),
    )
    refreshed = await refresh_due_collections(
        db_session, tmdb_client=fake_tmdb,
        collection_defs=[test_def],
    )
    assert refreshed == []
    fake_tmdb.trending_day.assert_not_called()
