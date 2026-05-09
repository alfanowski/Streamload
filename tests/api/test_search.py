"""Live search via TMDB."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from streamload.catalog.tmdb import TmdbItem


@pytest.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "user1", "email": "user1@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_search_returns_tmdb_results(api_client, authed):
    fake_results = [
        TmdbItem(tmdb_id=1, media_type="movie", title="Foo", year=2024,
                 poster_url="https://image.tmdb.org/t/p/w500/x.jpg"),
        TmdbItem(tmdb_id=2, media_type="tv", title="Bar", year=2023,
                 poster_url="https://image.tmdb.org/t/p/w500/y.jpg"),
    ]
    with patch("streamload.api.routes.search._build_tmdb_client") as mk:
        client = mk.return_value
        client.search_multi = AsyncMock(return_value=fake_results)
        r = await api_client.get("/api/search", params={"q": "foo"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 2


@pytest.mark.asyncio
async def test_search_empty_query_returns_400(api_client, authed):
    r = await api_client.get("/api/search", params={"q": ""})
    assert r.status_code == 422
