"""Tests for PATCH /api/me/profile."""
from __future__ import annotations

import httpx
import pytest


@pytest.fixture
async def authed_github(api_client: httpx.AsyncClient, monkeypatch) -> dict:
    """Returns body from a fresh GitHub login (profile incomplete)."""

    async def fake_fetch(*, token, http):
        from streamload.auth.github import GithubProfile
        return GithubProfile(id=7, login="seven", email="seven@example.com",
                             name=None, avatar_url=None)

    monkeypatch.setattr(
        "streamload.api.routes.auth_github.fetch_github_profile", fake_fetch,
    )
    r = await api_client.post("/api/auth/github", json={"access_token": "x"})
    assert r.status_code == 200
    return r.json()


@pytest.mark.asyncio
async def test_patch_profile_marks_profile_complete(api_client, authed_github):
    r = await api_client.patch("/api/me/profile", json={
        "first_name": "Andrea",
        "last_name": "Alfano",
        "birth_date": "1990-01-15",
        "gender": "male",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["first_name"] == "Andrea"
    assert body["last_name"] == "Alfano"
    assert body["birth_date"] == "1990-01-15"
    assert body["gender"] == "male"
    assert body["profile_complete"] is True


@pytest.mark.asyncio
async def test_patch_profile_rejects_unknown_gender(api_client, authed_github):
    r = await api_client.patch("/api/me/profile", json={
        "first_name": "X", "last_name": "Y",
        "birth_date": "1990-01-01", "gender": "alien",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_profile_rejects_future_birth_date(api_client, authed_github):
    r = await api_client.patch("/api/me/profile", json={
        "first_name": "X", "last_name": "Y",
        "birth_date": "2099-01-01", "gender": "female",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_profile_requires_session(api_client: httpx.AsyncClient):
    r = await api_client.patch("/api/me/profile", json={
        "first_name": "X", "last_name": "Y",
        "birth_date": "1990-01-01", "gender": "female",
    })
    assert r.status_code == 401
