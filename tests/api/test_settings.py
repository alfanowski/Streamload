"""Tests for per-user settings endpoint."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "setuser", "email": "set@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_get_settings_returns_defaults(api_client: httpx.AsyncClient, authed):
    r = await api_client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["audio_pref"] == "ita"
    assert body["subs_pref"] == "ita"
    assert body["autoplay_next"] is True
    assert body["quality_lock"] is None


@pytest.mark.asyncio
async def test_put_settings_echoes_back(api_client: httpx.AsyncClient, authed):
    payload = {
        "audio_pref": "eng",
        "subs_pref": "none",
        "autoplay_next": False,
        "quality_lock": "1080p",
    }
    r = await api_client.put("/api/settings", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["audio_pref"] == "eng"
    assert body["subs_pref"] == "none"
    assert body["autoplay_next"] is False
    assert body["quality_lock"] == "1080p"
