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
    assert r.json()["role"] == "admin"  # first user
    assert r.json()["email_verified"] is False

    # 2. /api/me works (cookie auto-set)
    r = await api_client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["username"] == "alice"

    # 3. Verify email
    async for db in gs():
        u = (await db.execute(select(User))).scalar_one()
        tok = await issue_token(db, user_id=u.id, purpose="verify_email")
        break
    r = await api_client.post("/api/auth/verify-email", json={"token": tok})
    assert r.status_code == 200

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
