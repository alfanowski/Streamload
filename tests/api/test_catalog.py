import os
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem, CatalogSource


@pytest.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "user1", "email": "user1@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_get_catalog_item(api_client, authed):
    async for db in gs():
        db.add(CatalogItem(tmdb_id=42, media_type="movie", title="Foo", year=2024))
        db.add(CatalogSource(
            tmdb_id=42, media_type="movie", service_short_name="sc",
            service_url="https://sc/42",
            service_media_id="42", quality_max_height=1080,
        ))
        await db.commit()
        break
    r = await api_client.get("/api/catalog/42")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Foo"
    assert len(body["sources"]) == 1
    assert body["sources"][0]["label"] == "StreamingCommunity"
    assert body["sources"][0]["score"] > 0


@pytest.mark.asyncio
async def test_get_catalog_item_404(api_client, authed):
    r = await api_client.get("/api/catalog/9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_catalog_requires_auth(api_client):
    r = await api_client.get("/api/catalog/42")
    assert r.status_code == 401
