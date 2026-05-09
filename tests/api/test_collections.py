from datetime import UTC, datetime

import httpx
import pytest

from streamload.db import get_session as gs
from streamload.db.models import (
    CatalogItem, Collection, CollectionItem,
)


@pytest.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "user1", "email": "user1@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_list_collections(api_client, authed):
    async for db in gs():
        db.add_all([
            Collection(id="a", title="A", sort_order=10, refresh_ttl_hours=24,
                       last_refreshed_at=datetime.now(UTC)),
            Collection(id="b", title="B", sort_order=20, refresh_ttl_hours=24,
                       last_refreshed_at=datetime.now(UTC)),
        ])
        await db.commit()
        break
    r = await api_client.get("/api/collections")
    assert r.status_code == 200
    body = r.json()
    assert [c["id"] for c in body] == ["a", "b"]


@pytest.mark.asyncio
async def test_get_collection_items(api_client, authed):
    async for db in gs():
        db.add_all([
            Collection(id="a", title="A", sort_order=10, refresh_ttl_hours=24,
                       last_refreshed_at=datetime.now(UTC)),
            CatalogItem(tmdb_id=1, media_type="movie", title="X", year=2024),
            CatalogItem(tmdb_id=2, media_type="movie", title="Y", year=2024),
            CollectionItem(collection_id="a", tmdb_id=2, media_type="movie", position=0),
            CollectionItem(collection_id="a", tmdb_id=1, media_type="movie", position=1),
        ])
        await db.commit()
        break
    r = await api_client.get("/api/collections/a")
    assert r.status_code == 200
    body = r.json()
    assert [i["tmdb_id"] for i in body["items"]] == [2, 1]


@pytest.mark.asyncio
async def test_get_unknown_collection_404(api_client, authed):
    r = await api_client.get("/api/collections/nope")
    assert r.status_code == 404
