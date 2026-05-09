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
