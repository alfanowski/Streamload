"""Tests for favorites endpoints."""
import httpx
import pytest
import pytest_asyncio

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem


@pytest_asyncio.fixture
async def authed_with_item(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "favuser", "email": "fav@x.com", "password": "Hunter2!secret",
    })
    async for db in gs():
        db.add(CatalogItem(tmdb_id=99, media_type="movie", title="Fav Movie"))
        await db.commit()
        break


@pytest.mark.asyncio
async def test_list_favorites_returns_empty_initially(api_client, authed_with_item):
    r = await api_client.get("/api/favorites")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_post_favorite_adds_and_get_returns_it(api_client, authed_with_item):
    r = await api_client.post("/api/favorites/99?media_type=movie")
    assert r.status_code == 201
    r = await api_client.get("/api/favorites")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["tmdb_id"] == 99
    assert body[0]["media_type"] == "movie"


@pytest.mark.asyncio
async def test_delete_favorite_removes_it(api_client, authed_with_item):
    await api_client.post("/api/favorites/99?media_type=movie")
    r = await api_client.delete("/api/favorites/99?media_type=movie")
    assert r.status_code == 204
    r = await api_client.get("/api/favorites")
    assert r.json() == []


@pytest.mark.asyncio
async def test_add_favorite_emits_event(api_client, authed_with_item):
    from sqlalchemy import select
    from streamload.db.models import Event

    await api_client.post("/api/favorites/99?media_type=movie")

    async for db in gs():
        rows = (await db.execute(
            select(Event).where(Event.event_type == "favorite.add")
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload == {"tmdb_id": 99, "media_type": "movie"}
        break


@pytest.mark.asyncio
async def test_remove_favorite_emits_event(api_client, authed_with_item):
    from sqlalchemy import select
    from streamload.db.models import Event

    await api_client.post("/api/favorites/99?media_type=movie")
    await api_client.delete("/api/favorites/99?media_type=movie")

    async for db in gs():
        types = [e.event_type for e in (await db.execute(
            select(Event)
        )).scalars().all()]
        assert "favorite.add" in types
        assert "favorite.remove" in types
        break
