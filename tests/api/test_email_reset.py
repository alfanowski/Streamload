"""Tests for password reset request + confirm endpoints."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from streamload.auth.email_tokens import issue_token
from streamload.auth.sessions import create_session
from streamload.db import get_session as db_get_session
from streamload.db.models import Session as SessionModel, User


@pytest.mark.asyncio
async def test_request_reset_returns_200_for_existing_email(api_client: httpx.AsyncClient):
    """Anti-enumeration: 200 returned even when the email exists."""
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    r = await api_client.post("/api/auth/request-password-reset", json={"email": "alice@x.com"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_request_reset_returns_200_for_unknown_email(api_client: httpx.AsyncClient):
    """Anti-enumeration: 200 also returned when no account with that email exists."""
    r = await api_client.post("/api/auth/request-password-reset", json={"email": "nobody@x.com"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_confirm_reset_changes_password(api_client: httpx.AsyncClient):
    """Valid token + new password → password is updated, old password no longer works."""
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    async for db in db_get_session():
        u = (await db.execute(select(User))).scalar_one()
        tok = await issue_token(db, user_id=u.id, purpose="reset_password")
        break

    r = await api_client.post("/api/auth/confirm-password-reset", json={
        "token": tok,
        "new_password": "NewPass99!strong",
    })
    assert r.status_code == 200

    # Old password should no longer work.
    r_old = await api_client.post("/api/auth/login", json={
        "username": "alice", "password": "Hunter2!secret",
    })
    assert r_old.status_code == 401

    # New password should work.
    r_new = await api_client.post("/api/auth/login", json={
        "username": "alice", "password": "NewPass99!strong",
    })
    assert r_new.status_code == 200


@pytest.mark.asyncio
async def test_confirm_reset_invalidates_existing_sessions(api_client: httpx.AsyncClient):
    """After a successful reset, all prior sessions for that user are deleted."""
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })

    # Create an extra session directly in DB.
    async for db in db_get_session():
        u = (await db.execute(select(User))).scalar_one()
        user_id = u.id
        await create_session(db, user_id=user_id)
        tok = await issue_token(db, user_id=user_id, purpose="reset_password")
        break

    r = await api_client.post("/api/auth/confirm-password-reset", json={
        "token": tok,
        "new_password": "NewPass99!strong",
    })
    assert r.status_code == 200

    # No sessions should remain for this user.
    async for db in db_get_session():
        sessions = (await db.execute(
            select(SessionModel).where(SessionModel.user_id == user_id)
        )).scalars().all()
        assert sessions == []
        break


@pytest.mark.asyncio
async def test_confirm_reset_with_invalid_token_returns_400(api_client: httpx.AsyncClient):
    """Bogus or expired token → 400."""
    r = await api_client.post("/api/auth/confirm-password-reset", json={
        "token": "totally-bogus-token",
        "new_password": "NewPass99!strong",
    })
    assert r.status_code == 400
