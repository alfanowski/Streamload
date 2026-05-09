"""Library: paginated catalog browse."""
from __future__ import annotations

import httpx
import pytest

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem


@pytest.fixture
async def authed_with_items(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "libuser", "email": "lib@x.com", "password": "Hunter2!secret",
    })
    async for db in gs():
        for i in range(5):
            db.add(CatalogItem(
                tmdb_id=100 + i,
                media_type="movie" if i < 3 else "tv",
                title=f"Movie {i}",
                year=2020 + i,
            ))
        await db.commit()
        break


@pytest.mark.asyncio
async def test_library_returns_paginated_results(api_client, authed_with_items):
    r = await api_client.get("/api/library", params={"page": 1, "per_page": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["per_page"] == 3
    assert len(body["items"]) == 3


@pytest.mark.asyncio
async def test_library_filters_by_media_type(api_client, authed_with_items):
    r = await api_client.get("/api/library", params={"media_type": "movie"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3  # 3 movies seeded
    assert all(item["media_type"] == "movie" for item in body["items"])


@pytest.mark.asyncio
async def test_library_pagination_returns_remaining_on_page_2(api_client, authed_with_items):
    r = await api_client.get("/api/library", params={"page": 2, "per_page": 3})
    body = r.json()
    assert len(body["items"]) == 2  # 5 total, page size 3, page 2 = 2 items


@pytest.mark.asyncio
async def test_library_requires_auth(api_client: httpx.AsyncClient):
    r = await api_client.get("/api/library")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_library_invalid_media_type_returns_422(api_client, authed_with_items):
    r = await api_client.get("/api/library", params={"media_type": "junk"})
    assert r.status_code == 422
