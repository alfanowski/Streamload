"""Auth dependency wires session cookie -> User."""
from __future__ import annotations

import httpx
import pytest

from streamload.auth.sessions import create_session
from streamload.db import get_session as db_get_session
from streamload.db.models import User


@pytest.mark.asyncio
async def test_protected_route_returns_401_without_cookie(api_client: httpx.AsyncClient):
    r = await api_client.get("/api/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_returns_user_with_valid_cookie(api_client: httpx.AsyncClient):
    # Seed a user and a session row.
    async for db in db_get_session():
        u = User(username="bob", email="bob@example.com")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        token = await create_session(db, user_id=u.id)
        break

    r = await api_client.get("/api/me", cookies={"session": token})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "bob"
    assert body["email"] == "bob@example.com"
