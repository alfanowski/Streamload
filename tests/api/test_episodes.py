"""Tests for TV episodes endpoint."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem, TvEpisode


@pytest_asyncio.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "epuser", "email": "ep@x.com", "password": "Hunter2!secret",
    })


@pytest_asyncio.fixture
async def authed_with_episodes(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "epuser", "email": "ep@x.com", "password": "Hunter2!secret",
    })
    async for db in gs():
        db.add(CatalogItem(tmdb_id=55, media_type="tv", title="Test Show"))
        db.add(TvEpisode(tmdb_id=55, season_number=1, episode_number=1, title="Pilot", runtime_minutes=45))
        db.add(TvEpisode(tmdb_id=55, season_number=1, episode_number=2, title="Ep 2", runtime_minutes=42))
        db.add(TvEpisode(tmdb_id=55, season_number=2, episode_number=1, title="S2E1", runtime_minutes=44))
        await db.commit()
        break


@pytest.mark.asyncio
async def test_episodes_empty_returns_empty_seasons(api_client: httpx.AsyncClient, authed):
    r = await api_client.get("/api/title/9999/episodes")
    assert r.status_code == 200
    body = r.json()
    assert body == {"seasons": []}


@pytest.mark.asyncio
async def test_episodes_lazy_ingests_from_tmdb_when_missing(
    api_client: httpx.AsyncClient, authed, monkeypatch,
):
    """A TV title with no episodes in the DB (e.g. The Simpsons) pulls them
    from TMDB on demand, caches them, and returns the full season list."""
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    from streamload.catalog.tmdb import TmdbItem

    async def fake_get_tv(self, tmdb_id):
        return TmdbItem(
            tmdb_id=tmdb_id, media_type="tv", title="The Simpsons",
            seasons_count=2,
        )

    async def fake_get_tv_season(self, tmdb_id, season_number):
        return {"episodes": [
            {"episode_number": 1, "name": f"S{season_number}E1", "runtime": 22},
            {"episode_number": 2, "name": f"S{season_number}E2", "runtime": 22},
        ]}

    monkeypatch.setattr(
        "streamload.api.routes.episodes.TmdbClient.get_tv", fake_get_tv,
    )
    monkeypatch.setattr(
        "streamload.api.routes.episodes.TmdbClient.get_tv_season",
        fake_get_tv_season,
    )

    r = await api_client.get("/api/title/456/episodes")
    assert r.status_code == 200
    seasons = r.json()["seasons"]
    assert len(seasons) == 2
    assert [s["season_number"] for s in seasons] == [1, 2]
    assert len(seasons[0]["episodes"]) == 2
    assert seasons[0]["episodes"][0]["title"] == "S1E1"


@pytest.mark.asyncio
async def test_episodes_populated_returns_seasons(api_client: httpx.AsyncClient, authed_with_episodes):
    r = await api_client.get("/api/title/55/episodes")
    assert r.status_code == 200
    body = r.json()
    seasons = body["seasons"]
    assert len(seasons) == 2
    s1 = seasons[0]
    assert s1["season_number"] == 1
    assert len(s1["episodes"]) == 2
    assert s1["episodes"][0]["title"] == "Pilot"
    assert s1["episodes"][0]["runtime_minutes"] == 45
    s2 = seasons[1]
    assert s2["season_number"] == 2
    assert len(s2["episodes"]) == 1
