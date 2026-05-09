"""Tests for the /settings endpoint (v3 — DB-backed)."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "set_user", "email": "set@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_get_settings_returns_defaults_for_new_user(api_client, authed):
    r = await api_client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["audio_pref_lang"] == "ita"
    assert body["subs_pref_lang"] == "ita"
    assert body["autoplay_next_episode"] is True
    assert body["skip_intro"] is True
    assert body["theme"] == "auto"
    assert body["locale"] == "it-IT"
    assert body["quality_cap_height"] is None


@pytest.mark.asyncio
async def test_put_settings_persists_changes(api_client, authed):
    r = await api_client.put("/api/settings", json={
        "audio_pref_lang": "eng",
        "subs_pref_lang": "ita",
        "autoplay_next_episode": False,
        "skip_intro": False,
        "theme": "dark",
        "locale": "en-US",
        "quality_cap_height": 1080,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["audio_pref_lang"] == "eng"
    assert body["theme"] == "dark"
    assert body["quality_cap_height"] == 1080

    # Round-trip: GET reflects what was PUT
    r = await api_client.get("/api/settings")
    body2 = r.json()
    assert body2["audio_pref_lang"] == "eng"
    assert body2["theme"] == "dark"


@pytest.mark.asyncio
async def test_put_settings_rejects_invalid_theme(api_client, authed):
    r = await api_client.put("/api/settings", json={
        "audio_pref_lang": "ita",
        "subs_pref_lang": "ita",
        "autoplay_next_episode": True,
        "skip_intro": True,
        "theme": "rainbow",
        "locale": "it-IT",
        "quality_cap_height": None,
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_settings_requires_auth(api_client):
    r = await api_client.get("/api/settings")
    assert r.status_code == 401
