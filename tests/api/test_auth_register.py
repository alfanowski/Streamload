"""User registration."""
from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_register_creates_user(api_client: httpx.AsyncClient):
    r = await api_client.post("/api/auth/register", json={
        "username": "alice",
        "email": "alice@example.com",
        "password": "Hunter2!secret",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "alice"
    # Email verification is auto-completed at registration on this private platform.
    assert body["email_verified"] is True


@pytest.mark.asyncio
async def test_first_user_is_role_user(api_client: httpx.AsyncClient):
    """Self-service registration always creates a regular user.
    The admin is provisioned separately at boot via STREAMLOAD_ADMIN_* env vars."""
    r = await api_client.post("/api/auth/register", json={
        "username": "first", "email": "first@x.com", "password": "Hunter2!secret",
    })
    assert r.status_code == 201
    assert r.json()["role"] == "user"


@pytest.mark.asyncio
async def test_subsequent_users_are_role_user(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "first", "email": "first@x.com", "password": "Hunter2!secret",
    })
    r = await api_client.post("/api/auth/register", json={
        "username": "second", "email": "second@x.com", "password": "Hunter2!secret",
    })
    assert r.json()["role"] == "user"


@pytest.mark.asyncio
async def test_register_rejects_duplicate_username(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "a@x.com", "password": "Hunter2!secret",
    })
    r = await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "b@x.com", "password": "Hunter2!secret",
    })
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_register_rejects_invalid_email(api_client: httpx.AsyncClient):
    r = await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "not-an-email", "password": "Hunter2!secret",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_short_password(api_client: httpx.AsyncClient):
    r = await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "12",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_sets_session_cookie(api_client: httpx.AsyncClient):
    r = await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    assert "session" in r.cookies
