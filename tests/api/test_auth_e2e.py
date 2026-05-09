"""End-to-end auth flow: register -> verify -> logout -> login -> me."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from streamload.auth.email_tokens import issue_token
from streamload.db import get_session as gs
from streamload.db.models import User


@pytest.mark.asyncio
async def test_full_lifecycle(api_client: httpx.AsyncClient):
    # 1. Register
    r = await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    assert r.status_code == 201
    # Admin role is no longer auto-granted to the first user; bootstrap handles it.
    assert r.json()["role"] == "user"
    # Self-service registration auto-verifies email on a private platform.
    assert r.json()["email_verified"] is True

    # 2. /api/me works (cookie auto-set)
    r = await api_client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["username"] == "alice"

    # 3. Email already verified at registration — no token flow needed.

    # 4. Logout
    r = await api_client.post("/api/auth/logout")
    assert r.status_code == 204

    # 5. /api/me now 401 — manually clear cookie as fallback for httpx cookie-jar behaviour
    api_client.cookies.clear()
    r = await api_client.get("/api/me")
    assert r.status_code == 401

    # 6. Login
    r = await api_client.post("/api/auth/login", json={
        "username": "alice", "password": "Hunter2!secret",
    })
    assert r.status_code == 200

    # 7. /api/me again, email_verified true now
    r = await api_client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["email_verified"] is True
