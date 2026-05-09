"""Tests for /next-up endpoint."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem, TvEpisode


@pytest_asyncio.fixture
async def authed_with_series(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "nu_user", "email": "nu@x.com", "password": "Hunter2!secret",
    })
    async for db in gs():
        db.add(CatalogItem(tmdb_id=99, media_type="tv", title="Show", seasons_count=2))
        db.add_all([
            TvEpisode(tmdb_id=99, media_type="tv", season_number=1, episode_number=1, title="S1E1"),
            TvEpisode(tmdb_id=99, media_type="tv", season_number=1, episode_number=2, title="S1E2"),
            TvEpisode(tmdb_id=99, media_type="tv", season_number=1, episode_number=3, title="S1E3"),
            TvEpisode(tmdb_id=99, media_type="tv", season_number=2, episode_number=1, title="S2E1"),
        ])
        await db.commit()
        break


@pytest.mark.asyncio
async def test_next_up_returns_next_episode_in_same_season(api_client, authed_with_series):
    r = await api_client.get("/api/next-up/99?season=1&episode=2")
    assert r.status_code == 200
    body = r.json()
    assert body["season_number"] == 1
    assert body["episode_number"] == 3


@pytest.mark.asyncio
async def test_next_up_jumps_to_next_season_when_at_finale(api_client, authed_with_series):
    r = await api_client.get("/api/next-up/99?season=1&episode=3")
    assert r.status_code == 200
    body = r.json()
    assert body["season_number"] == 2
    assert body["episode_number"] == 1


@pytest.mark.asyncio
async def test_next_up_returns_204_at_series_end(api_client, authed_with_series):
    r = await api_client.get("/api/next-up/99?season=2&episode=1")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_next_up_404_for_unknown_title(api_client, authed_with_series):
    r = await api_client.get("/api/next-up/9999?season=1&episode=1")
    assert r.status_code == 404
