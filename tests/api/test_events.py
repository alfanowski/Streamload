"""Tests for /events telemetry endpoint."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from streamload.db import get_session as gs


@pytest_asyncio.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "evt_user", "email": "evt@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_post_events_accepts_valid_batch(api_client, authed):
    r = await api_client.post("/api/events", json={
        "app_version": "0.3.0",
        "events": [
            {"event_type": "app.start", "payload": {"app_version": "0.3.0", "os": "macos", "locale": "it-IT"}},
            {"event_type": "catalog.view", "payload": {"tmdb_id": 1396, "media_type": "tv"}},
        ],
    })
    assert r.status_code == 202

    from sqlalchemy import select
    from streamload.db.models import Event
    async for db in gs():
        rows = (await db.execute(select(Event).order_by(Event.id))).scalars().all()
        assert len(rows) == 2
        assert rows[0].event_type == "app.start"
        assert rows[0].user_id is not None
        assert rows[0].app_version == "0.3.0"
        assert rows[1].event_type == "catalog.view"
        assert rows[1].payload == {"tmdb_id": 1396, "media_type": "tv"}
        break


@pytest.mark.asyncio
async def test_post_events_rejects_unknown_event_type(api_client, authed):
    r = await api_client.post("/api/events", json={
        "events": [
            {"event_type": "totally.invented", "payload": {}},
        ],
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_events_rejects_oversized_batch(api_client, authed):
    r = await api_client.post("/api/events", json={
        "events": [
            {"event_type": "app.start", "payload": {}}
            for _ in range(101)
        ],
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_events_requires_auth(api_client):
    r = await api_client.post("/api/events", json={"events": []})
    assert r.status_code == 401
