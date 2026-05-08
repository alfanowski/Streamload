"""Verify the health endpoint returns service metadata."""
from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_health_returns_200(api_client: httpx.AsyncClient):
    r = await api_client.get("/api/health")
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "ok"
    assert "version" in payload


@pytest.mark.asyncio
async def test_version_endpoint(api_client: httpx.AsyncClient):
    r = await api_client.get("/api/version")
    assert r.status_code == 200
    payload = r.json()
    assert "version" in payload
    assert "git_sha" in payload
