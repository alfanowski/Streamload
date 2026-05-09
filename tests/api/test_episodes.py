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
