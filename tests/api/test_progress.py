"""Tests for watch progress endpoints."""
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem, WatchProgress


@pytest_asyncio.fixture
async def authed_with_item(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "proguser", "email": "prog@x.com", "password": "Hunter2!secret",
    })
    async for db in gs():
        db.add(CatalogItem(tmdb_id=42, media_type="movie", title="X"))
        await db.commit()
        break


@pytest.mark.asyncio
async def test_post_progress_creates_row(api_client, authed_with_item):
    r = await api_client.post("/api/progress", json={
        "tmdb_id": 42, "media_type": "movie", "position_seconds": 120, "duration_seconds": 7200,
    })
    assert r.status_code == 200
    async for db in gs():
        row = (await db.execute(select(WatchProgress))).scalar_one()
        assert row.position_seconds == 120
        assert row.completed is False
        break


@pytest.mark.asyncio
async def test_post_progress_marks_completed_above_90pct(api_client, authed_with_item):
    r = await api_client.post("/api/progress", json={
        "tmdb_id": 42, "media_type": "movie", "position_seconds": 6500, "duration_seconds": 7200,
    })
    assert r.status_code == 200
    async for db in gs():
        row = (await db.execute(select(WatchProgress))).scalar_one()
        assert row.completed is True
        break


@pytest.mark.asyncio
async def test_get_continue_watching_returns_uncompleted(api_client, authed_with_item):
    await api_client.post("/api/progress", json={
        "tmdb_id": 42, "media_type": "movie", "position_seconds": 120, "duration_seconds": 7200,
    })
    r = await api_client.get("/api/progress/continue-watching")
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["tmdb_id"] == 42


@pytest.mark.asyncio
async def test_continue_watching_dedupes_series_to_one_entry(
    api_client, authed_with_item,
):
    """Two in-progress episodes of the same series collapse to ONE entry
    (the most recent), instead of duplicating the show in the row."""
    async for db in gs():
        db.add(CatalogItem(tmdb_id=99, media_type="tv", title="The Office"))
        await db.commit()
        break
    # Watched two episodes a bit, neither finished.
    await api_client.post("/api/progress", json={
        "tmdb_id": 99, "media_type": "tv", "season_number": 1,
        "episode_number": 1, "position_seconds": 200, "duration_seconds": 1400,
    })
    await api_client.post("/api/progress", json={
        "tmdb_id": 99, "media_type": "tv", "season_number": 1,
        "episode_number": 2, "position_seconds": 120, "duration_seconds": 1400,
    })
    r = await api_client.get("/api/progress/continue-watching")
    items = r.json()["items"]
    series = [i for i in items if i["tmdb_id"] == 99]
    assert len(series) == 1
    # Keeps the most recently updated episode (E2).
    assert series[0]["episode_number"] == 2


@pytest.mark.asyncio
async def test_title_progress_returns_every_episode(api_client, authed_with_item):
    """The per-title endpoint returns ALL episodes' progress (incl. completed)
    so the title page can draw watch bars + 'seen' ticks."""
    async for db in gs():
        db.add(CatalogItem(tmdb_id=77, media_type="tv", title="Lost"))
        await db.commit()
        break
    await api_client.post("/api/progress", json={
        "tmdb_id": 77, "media_type": "tv", "season_number": 1,
        "episode_number": 1, "position_seconds": 1300, "duration_seconds": 1400,
    })  # finished → completed
    await api_client.post("/api/progress", json={
        "tmdb_id": 77, "media_type": "tv", "season_number": 1,
        "episode_number": 2, "position_seconds": 300, "duration_seconds": 1400,
    })  # in progress
    r = await api_client.get("/api/progress/title/77?media_type=tv")
    assert r.status_code == 200
    items = {(i["season_number"], i["episode_number"]): i
             for i in r.json()["items"]}
    assert items[(1, 1)]["completed"] is True
    assert items[(1, 2)]["completed"] is False
    assert items[(1, 2)]["position_seconds"] == 300


@pytest.mark.asyncio
async def test_remove_continue_watching(api_client, authed_with_item):
    await api_client.post("/api/progress", json={
        "tmdb_id": 42, "media_type": "movie",
        "position_seconds": 120, "duration_seconds": 7200,
    })
    r = await api_client.delete(
        "/api/progress/continue-watching/42?media_type=movie")
    assert r.status_code == 200
    body = (await api_client.get("/api/progress/continue-watching")).json()
    assert all(i["tmdb_id"] != 42 for i in body["items"])


@pytest.mark.asyncio
async def test_post_progress_inserts_watch_history_on_completion(api_client, authed_with_item):
    from sqlalchemy import select
    from streamload.db.models import WatchHistory
    # >90% triggers completion
    await api_client.post("/api/progress", json={
        "tmdb_id": 42, "media_type": "movie",
        "position_seconds": 6500, "duration_seconds": 7200,
    })
    async for db in gs():
        rows = (await db.execute(select(WatchHistory))).scalars().all()
        assert len(rows) == 1
        assert rows[0].tmdb_id == 42
        assert rows[0].media_type == "movie"
        break


@pytest.mark.asyncio
async def test_post_progress_no_history_when_not_completed(api_client, authed_with_item):
    from sqlalchemy import select
    from streamload.db.models import WatchHistory
    await api_client.post("/api/progress", json={
        "tmdb_id": 42, "media_type": "movie",
        "position_seconds": 100, "duration_seconds": 7200,
    })
    async for db in gs():
        rows = (await db.execute(select(WatchHistory))).scalars().all()
        assert rows == []
        break
