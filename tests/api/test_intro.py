"""Tests for skip intro/outro marker endpoint."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem, IntroMarker


@pytest_asyncio.fixture
async def authed_with_marker(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "introuser", "email": "intro@x.com", "password": "Hunter2!secret",
    })
    async for db in gs():
        db.add(CatalogItem(tmdb_id=42, media_type="tv", title="X"))
        db.add(IntroMarker(
            tmdb_id=42, season_number=1, intro_start_seconds=0,
            intro_end_seconds=85, detected_by="fingerprint", confidence=0.92,
        ))
        await db.commit()
        break


@pytest.mark.asyncio
async def test_get_intro_marker(api_client: httpx.AsyncClient, authed_with_marker):
    r = await api_client.get("/api/intro/42/s1")
    assert r.status_code == 200
    body = r.json()
    assert body["intro_start"] == 0
    assert body["intro_end"] == 85


@pytest.mark.asyncio
async def test_get_intro_marker_missing_returns_204(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "introuser", "email": "intro@x.com", "password": "Hunter2!secret",
    })
    r = await api_client.get("/api/intro/9999/s1")
    assert r.status_code == 204
