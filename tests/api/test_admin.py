"""Tests for admin dashboard endpoints."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select


async def _promote_to_admin(username: str) -> None:
    """Direct-DB promotion (bypasses self-service registration which always creates 'user')."""
    from streamload.db.models import User
    from streamload.db.session import _session_factory
    async with _session_factory() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one()
        user.role = "admin"
        await db.commit()


@pytest_asyncio.fixture
async def admin_client(api_client: httpx.AsyncClient):
    """Register a user and promote them to admin via direct DB access."""
    await api_client.post("/api/auth/register", json={
        "username": "adminuser", "email": "admin@x.com", "password": "Hunter2!secret",
    })
    await _promote_to_admin("adminuser")
    return api_client


@pytest_asyncio.fixture
async def nonadmin_client(api_client: httpx.AsyncClient):
    """Register a regular (non-admin) user."""
    await api_client.post("/api/auth/register", json={
        "username": "regularuser", "email": "regular@x.com", "password": "Hunter2!secret",
    })
    return api_client


@pytest.mark.asyncio
async def test_admin_can_list_users(api_client: httpx.AsyncClient, admin_client):
    r = await api_client.get("/api/admin/users")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    assert body[0]["username"] == "adminuser"
    assert body[0]["role"] == "admin"


@pytest.mark.asyncio
async def test_non_admin_gets_403(api_client: httpx.AsyncClient, nonadmin_client):
    r = await api_client.get("/api/admin/users")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_promote_user(api_client: httpx.AsyncClient, admin_client):
    import httpx as _httpx
    from streamload.api.app import create_app
    from streamload.db import init as db_init, shutdown as db_shutdown
    import os

    test_url = os.environ.get(
        "DATABASE_URL_TEST",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test",
    )
    db_init(test_url)
    app = create_app()
    transport = _httpx.ASGITransport(app=app)
    async with _httpx.AsyncClient(transport=transport, base_url="http://test") as c2:
        r = await c2.post("/api/auth/register", json={
            "username": "promoteuser", "email": "promote@x.com", "password": "Hunter2!secret",
        })
        assert r.status_code == 201

    r = await api_client.get("/api/admin/users")
    users = r.json()
    regular = next((u for u in users if u["username"] == "promoteuser"), None)
    assert regular is not None
    user_id = regular["id"]
    assert regular["role"] == "user"

    r = await api_client.put(f"/api/admin/users/{user_id}/role", json={"role": "admin"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    r = await api_client.get("/api/admin/users")
    users = r.json()
    updated = next(u for u in users if u["username"] == "promoteuser")
    assert updated["role"] == "admin"
    await db_shutdown()


@pytest.mark.asyncio
async def test_admin_can_disable_user(api_client: httpx.AsyncClient, admin_client):
    """Disabled users can't log in and have all sessions revoked."""
    # Register a target user.
    await api_client.post("/api/auth/logout")
    await api_client.post("/api/auth/register", json={
        "username": "victim", "email": "victim@x.com", "password": "Hunter2!secret",
    })
    await api_client.post("/api/auth/logout")

    # Re-login as admin.
    r = await api_client.post("/api/auth/login", json={
        "username": "adminuser", "password": "Hunter2!secret",
    })
    assert r.status_code == 200

    # Disable the victim.
    users = (await api_client.get("/api/admin/users")).json()
    victim_id = next(u["id"] for u in users if u["username"] == "victim")
    r = await api_client.post(f"/api/admin/users/{victim_id}/disable")
    assert r.status_code == 200

    # Victim can no longer log in.
    r = await api_client.post("/api/auth/logout")
    r = await api_client.post("/api/auth/login", json={
        "username": "victim", "password": "Hunter2!secret",
    })
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_demote_last_admin(api_client: httpx.AsyncClient, admin_client):
    users = (await api_client.get("/api/admin/users")).json()
    admin_id = next(u["id"] for u in users if u["username"] == "adminuser")
    r = await api_client.put(f"/api/admin/users/{admin_id}/role", json={"role": "user"})
    assert r.status_code == 400
