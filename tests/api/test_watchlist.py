"""Tests for watchlist endpoints."""
import httpx
import pytest
import pytest_asyncio

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem


@pytest_asyncio.fixture
async def authed_with_item(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "wluser", "email": "wl@x.com", "password": "Hunter2!secret",
    })
    async for db in gs():
        db.add(CatalogItem(tmdb_id=77, media_type="tv", title="Watch TV"))
        await db.commit()
        break


@pytest.mark.asyncio
async def test_list_watchlist_returns_empty_initially(api_client, authed_with_item):
    r = await api_client.get("/api/watchlist")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_post_watchlist_adds_and_get_returns_it(api_client, authed_with_item):
    r = await api_client.post("/api/watchlist/77")
    assert r.status_code == 201
    r = await api_client.get("/api/watchlist")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["tmdb_id"] == 77


@pytest.mark.asyncio
async def test_delete_watchlist_removes_it(api_client, authed_with_item):
    await api_client.post("/api/watchlist/77")
    r = await api_client.delete("/api/watchlist/77")
    assert r.status_code == 204
    r = await api_client.get("/api/watchlist")
    assert r.json() == []
