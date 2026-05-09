"""Tests for admin dashboard endpoints."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def admin_client(api_client: httpx.AsyncClient):
    """Register first user (auto-promoted to admin)."""
    await api_client.post("/api/auth/register", json={
        "username": "adminuser", "email": "admin@x.com", "password": "Hunter2!secret",
    })
    return api_client


@pytest_asyncio.fixture
async def nonadmin_client(api_client: httpx.AsyncClient):
    """Register two users; second user is a regular user."""
    # First user becomes admin
    await api_client.post("/api/auth/register", json={
        "username": "adminuser", "email": "admin@x.com", "password": "Hunter2!secret",
    })
    # Log out admin
    await api_client.post("/api/auth/logout")
    # Register second user (regular)
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
    # Register a second (regular) user via separate client session
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

    # Now get the user id from list
    r = await api_client.get("/api/admin/users")
    users = r.json()
    regular = next((u for u in users if u["username"] == "promoteuser"), None)
    assert regular is not None
    user_id = regular["id"]
    assert regular["role"] == "user"

    # Promote
    r = await api_client.put(f"/api/admin/users/{user_id}/role", json={"role": "admin"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # Verify
    r = await api_client.get("/api/admin/users")
    users = r.json()
    updated = next(u for u in users if u["username"] == "promoteuser")
    assert updated["role"] == "admin"
    await db_shutdown()
