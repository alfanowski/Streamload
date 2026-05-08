from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from streamload.auth.email_tokens import issue_token
from streamload.db import get_session as db_get_session
from streamload.db.models import User


@pytest.mark.asyncio
async def test_verify_with_valid_token_sets_email_verified_at(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    # Issue another token directly to test verify (the registration one was sent via dry-run email).
    async for db in db_get_session():
        u = (await db.execute(select(User))).scalar_one()
        tok = await issue_token(db, user_id=u.id, purpose="verify_email")
        break
    r = await api_client.post(f"/api/auth/verify-email", json={"token": tok})
    assert r.status_code == 200

    async for db in db_get_session():
        u = (await db.execute(select(User))).scalar_one()
        assert u.email_verified_at is not None
        break


@pytest.mark.asyncio
async def test_verify_with_invalid_token_returns_400(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    r = await api_client.post(f"/api/auth/verify-email", json={"token": "bogus"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_verify_is_idempotent_safe(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    async for db in db_get_session():
        u = (await db.execute(select(User))).scalar_one()
        tok = await issue_token(db, user_id=u.id, purpose="verify_email")
        break
    r1 = await api_client.post(f"/api/auth/verify-email", json={"token": tok})
    r2 = await api_client.post(f"/api/auth/verify-email", json={"token": tok})
    assert r1.status_code == 200
    assert r2.status_code == 400  # token already consumed
