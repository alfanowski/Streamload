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


@pytest.mark.asyncio
async def test_search_inserts_search_history_and_event(api_client: httpx.AsyncClient):
    import hashlib
    from sqlalchemy import select
    from streamload.db.models import Event, SearchHistory
    from streamload.db import get_session as gs

    await api_client.post("/api/auth/register", json={
        "username": "src_user", "email": "src@x.com", "password": "Hunter2!secret",
    })
    # The search route writes search_history + emits event regardless of
    # whether the TMDB upstream call succeeds (the bookkeeping is in a
    # try/finally). Status code is best-effort: 200 if TMDB_API_KEY is set in
    # the test env, otherwise still 200 with empty results.
    r = await api_client.get("/api/search?q=inception")
    assert r.status_code == 200

    async for db in gs():
        history = (await db.execute(select(SearchHistory))).scalars().all()
        assert len(history) >= 1
        assert history[0].query_text == "inception"
        assert history[0].query_hash == hashlib.sha256(b"inception").hexdigest()

        events = (await db.execute(
            select(Event).where(Event.event_type == "search.run")
        )).scalars().all()
        assert len(events) == 1
        assert events[0].payload["query_hash"] == hashlib.sha256(b"inception").hexdigest()
        break
