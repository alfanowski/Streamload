from __future__ import annotations

import httpx
import pytest


@pytest.fixture
async def registered_user(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    # clear cookies to start fresh
    api_client.cookies.clear()


@pytest.mark.asyncio
async def test_login_with_valid_credentials_sets_cookie(api_client, registered_user):
    r = await api_client.post("/api/auth/login", json={
        "username": "alice", "password": "Hunter2!secret",
    })
    assert r.status_code == 200
    assert "session" in r.cookies


@pytest.mark.asyncio
async def test_login_with_email_works(api_client, registered_user):
    r = await api_client.post("/api/auth/login", json={
        "username": "alice@x.com", "password": "Hunter2!secret",
    })
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401(api_client, registered_user):
    r = await api_client.post("/api/auth/login", json={
        "username": "alice", "password": "wrong",
    })
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_with_unknown_user_returns_401(api_client, registered_user):
    r = await api_client.post("/api/auth/login", json={
        "username": "ghost", "password": "Hunter2!secret",
    })
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_updates_last_login_at(api_client, registered_user):
    from sqlalchemy import select
    from streamload.db import get_session as gs
    from streamload.db.models import User
    await api_client.post("/api/auth/login", json={
        "username": "alice", "password": "Hunter2!secret",
    })
    async for db in gs():
        u = (await db.execute(select(User))).scalar_one()
        assert u.last_login_at is not None
        break


@pytest.mark.asyncio
async def test_login_success_emits_telemetry_event(api_client: httpx.AsyncClient):
    from sqlalchemy import select
    from streamload.db.models import Event
    from streamload.db import get_session as gs

    await api_client.post("/api/auth/register", json={
        "username": "tel_user", "email": "tel@x.com", "password": "Hunter2!secret",
    })
    await api_client.post("/api/auth/logout")
    await api_client.post("/api/auth/login", json={
        "username": "tel_user", "password": "Hunter2!secret",
    })

    async for db in gs():
        types = [e.event_type for e in (await db.execute(
            select(Event).order_by(Event.id)
        )).scalars().all()]
        assert "auth.login_success" in types
        assert "auth.logout" in types
        break


@pytest.mark.asyncio
async def test_login_failed_emits_telemetry_event(api_client: httpx.AsyncClient):
    from sqlalchemy import select
    from streamload.db.models import Event
    from streamload.db import get_session as gs

    await api_client.post("/api/auth/register", json={
        "username": "tel_user2", "email": "tel2@x.com", "password": "Hunter2!secret",
    })
    await api_client.post("/api/auth/logout")
    r = await api_client.post("/api/auth/login", json={
        "username": "tel_user2", "password": "wrong-password",
    })
    assert r.status_code == 401

    async for db in gs():
        types = [e.event_type for e in (await db.execute(
            select(Event)
        )).scalars().all()]
        assert "auth.login_failed" in types
        break
