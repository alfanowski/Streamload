import os
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem


@pytest.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "user1", "email": "user1@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_get_catalog_item(api_client, authed):
    async for db in gs():
        db.add(CatalogItem(tmdb_id=42, media_type="movie", title="Foo", year=2024))
        await db.commit()
        break
    r = await api_client.get("/api/catalog/42?media_type=movie")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Foo"
    # v3: server never knows sources — they live in the client.
    assert body["sources"] == []


@pytest.mark.asyncio
async def test_get_catalog_item_404(api_client, authed):
    r = await api_client.get("/api/catalog/9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_catalog_requires_auth(api_client):
    r = await api_client.get("/api/catalog/42")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_videos_filters_to_youtube(api_client, authed, monkeypatch):
    """The endpoint returns only YouTube results and strips non-YouTube sites."""
    from unittest.mock import AsyncMock

    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_get_videos(self, tmdb_id, *, media_type):
        return [
            {"key": "yt1", "site": "YouTube", "type": "Trailer", "official": True, "name": "Main"},
            {"key": "vm1", "site": "Vimeo", "type": "Trailer", "official": True, "name": "Skip"},
            {"key": "yt2", "site": "YouTube", "type": "Teaser", "official": False, "name": "Teaser"},
        ]

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_videos",
        fake_get_videos,
    )
    r = await api_client.get("/api/catalog/1396/videos?media_type=tv")
    assert r.status_code == 200
    body = r.json()
    assert [v["key"] for v in body] == ["yt1", "yt2"]
    assert all(v["site"] == "YouTube" for v in body)


@pytest.mark.asyncio
async def test_get_videos_bad_media_type_400(api_client, authed):
    r = await api_client.get("/api/catalog/1396/videos?media_type=bogus")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_get_videos_requires_auth(api_client):
    r = await api_client.get("/api/catalog/1396/videos?media_type=movie")
    assert r.status_code == 401
