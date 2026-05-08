"""Passkey registration challenge generation + verify."""
from __future__ import annotations

import httpx
import pytest


@pytest.fixture
async def logged_in_user(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_registration_options_requires_auth(api_client: httpx.AsyncClient):
    api_client.cookies.clear()
    r = await api_client.post("/api/auth/passkey/registration-options")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_registration_options_returns_challenge(api_client, logged_in_user):
    r = await api_client.post("/api/auth/passkey/registration-options",
                              json={"nickname": "iPhone"})
    assert r.status_code == 200
    body = r.json()
    assert "challenge" in body
    assert body["rp"]["name"]
    assert "user" in body and "id" in body["user"]


@pytest.mark.asyncio
async def test_authentication_options_returns_challenge_no_auth_needed(api_client, logged_in_user):
    api_client.cookies.clear()
    r = await api_client.post("/api/auth/passkey/authentication-options",
                              json={"username": "alice"})
    assert r.status_code == 200
    body = r.json()
    assert "challenge" in body


@pytest.mark.asyncio
async def test_authentication_options_for_unknown_user_returns_decoy(api_client):
    r = await api_client.post("/api/auth/passkey/authentication-options",
                              json={"username": "ghost"})
    # Anti-enumeration: still return 200 with a decoy challenge
    assert r.status_code == 200
