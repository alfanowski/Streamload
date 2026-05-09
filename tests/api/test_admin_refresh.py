import httpx
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
async def admin_authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "admin", "email": "a@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_admin_refresh_unknown_collection_404(api_client, admin_authed):
    r = await api_client.post("/api/admin/catalog/refresh/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_refresh_requires_admin(api_client):
    # Register two users; second is non-admin
    await api_client.post("/api/auth/register", json={
        "username": "first", "email": "f@x.com", "password": "Hunter2!secret",
    })
    api_client.cookies.clear()
    await api_client.post("/api/auth/register", json={
        "username": "second", "email": "s@x.com", "password": "Hunter2!secret",
    })
    r = await api_client.post("/api/admin/catalog/refresh/trending-day")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_refresh_runs_when_admin(api_client, admin_authed):
    with patch("streamload.api.routes.catalog._refresh_one") as mk:
        mk.return_value = AsyncMock(return_value=None)
        r = await api_client.post("/api/admin/catalog/refresh/trending-day")
        assert r.status_code in (200, 202)
