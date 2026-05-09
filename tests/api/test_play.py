"""Playback session creation endpoint tests."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from unittest.mock import AsyncMock, MagicMock, patch

from streamload.auth.email_tokens import issue_token
from streamload.db import get_session as gs
from streamload.db.models import CatalogItem, CatalogSource, User


async def _register_and_verify(api_client: httpx.AsyncClient) -> None:
    """Register a user and verify their email so they can play."""
    await api_client.post("/api/auth/register", json={
        "username": "playuser", "email": "playuser@x.com", "password": "Hunter2!secret",
    })
    async for db in gs():
        u = (await db.execute(select(User).where(User.email == "playuser@x.com"))).scalar_one()
        tok = await issue_token(db, user_id=u.id, purpose="verify_email")
        break
    await api_client.post("/api/auth/verify-email", json={"token": tok})


@pytest.mark.asyncio
async def test_play_creates_session(api_client: httpx.AsyncClient):
    await _register_and_verify(api_client)

    async for db in gs():
        db.add(CatalogItem(tmdb_id=42, media_type="movie", title="X", year=2024))
        db.add(CatalogSource(
            tmdb_id=42, service_short_name="sc", service_url="https://sc/42",
            service_media_id="42", quality_max_height=1080,
        ))
        await db.commit()
        break

    bundle = MagicMock()
    bundle.manifest_url = "https://vix/master.m3u8"
    bundle.extra_headers = {}
    bundle.is_drm = False
    bundle.drm_keys = None
    bundle.subtitles = []

    with patch("streamload.api.routes.play._get_service") as mk:
        svc = MagicMock()
        svc.short_name = "sc"
        svc.get_streams_async = AsyncMock(return_value=bundle)
        mk.return_value = svc
        r = await api_client.post("/api/play/42")

    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert body["master_url"].startswith("/stream/")
    assert body["current_server"] == "StreamingCommunity"


@pytest.mark.asyncio
async def test_play_unknown_title_404(api_client: httpx.AsyncClient):
    await _register_and_verify(api_client)
    r = await api_client.post("/api/play/9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_play_blocks_user_with_email_required_unverified(api_client: httpx.AsyncClient):
    """If an admin sets email_required=True and the user is unverified, play 403s."""
    r = await api_client.post("/api/auth/register", json={
        "username": "unveri", "email": "unveri@x.com", "password": "Hunter2!secret",
    })
    assert r.status_code == 201

    # Force email_required=True and clear verification.
    async for db in gs():
        u = (await db.execute(select(User).where(User.username == "unveri"))).scalar_one()
        u.email_verified_at = None
        u.email_required = True
        await db.commit()
        break

    async for db in gs():
        db.add(CatalogItem(tmdb_id=42, media_type="movie", title="X"))
        db.add(CatalogSource(
            tmdb_id=42, service_short_name="sc", service_url="https://sc/42",
            service_media_id="42",
        ))
        await db.commit()
        break
    r = await api_client.post("/api/play/42")
    assert r.status_code == 403
    assert "email" in r.json()["detail"].lower()
