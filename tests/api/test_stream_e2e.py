"""End-to-end streaming proxy lifecycle integration test."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from unittest.mock import AsyncMock, MagicMock, patch

from streamload.auth.email_tokens import issue_token
from streamload.db import get_session as gs
from streamload.db.models import CatalogItem, CatalogSource, User

_FAKE_MASTER = (
    "#EXTM3U\n"
    "#EXT-X-STREAM-INF:BANDWIDTH=2150000,RESOLUTION=1280x720\n"
    "https://upstream/playlist?type=video&rendition=720p&token=abc\n"
)

_FAKE_MEDIA = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:3\n"
    "#EXT-X-TARGETDURATION:6\n"
    "#EXTINF:5.5,\n"
    "https://upstream/seg-001.ts\n"
    "#EXTINF:5.5,\n"
    "https://upstream/seg-002.ts\n"
    "#EXT-X-ENDLIST\n"
)


@pytest.mark.asyncio
async def test_full_proxy_lifecycle(api_client: httpx.AsyncClient):
    # 1. Register and verify user
    await api_client.post("/api/auth/register", json={
        "username": "e2euser", "email": "e2euser@x.com", "password": "Hunter2!secret",
    })
    async for db in gs():
        u = (await db.execute(
            select(User).where(User.email == "e2euser@x.com")
        )).scalar_one()
        tok = await issue_token(db, user_id=u.id, purpose="verify_email")
        break
    r = await api_client.post("/api/auth/verify-email", json={"token": tok})
    assert r.status_code == 200

    # 2. Insert catalog item + source
    async for db in gs():
        db.add(CatalogItem(tmdb_id=99, media_type="movie", title="E2E Movie", year=2025))
        db.add(CatalogSource(
            tmdb_id=99, service_short_name="sc", service_url="https://sc/99",
            service_media_id="99", quality_max_height=None,
        ))
        await db.commit()
        break

    # 3. Mock service get_streams_async
    bundle = MagicMock()
    bundle.manifest_url = "https://upstream/master.m3u8"
    bundle.extra_headers = {"Referer": "https://upstream"}
    bundle.is_drm = False
    bundle.drm_keys = None
    bundle.subtitles = []

    with patch("streamload.api.routes.play._get_service") as mock_svc_factory:
        svc = MagicMock()
        svc.short_name = "sc"
        svc.get_streams_async = AsyncMock(return_value=bundle)
        mock_svc_factory.return_value = svc

        # 4 + 5. POST /api/play/99 → get session
        r = await api_client.post("/api/play/99")

    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    session_id = body["session_id"]
    master_url = body["master_url"]
    assert master_url == f"/stream/{session_id}/master.m3u8"

    # 6. GET /stream/{session}/master.m3u8 with mocked upstream fetch
    with patch(
        "streamload.api.routes.stream._fetch_upstream_text",
        return_value=_FAKE_MASTER,
    ):
        r = await api_client.get(f"/stream/{session_id}/master.m3u8")

    assert r.status_code == 200
    assert "#EXTM3U" in r.text
    assert f"/stream/{session_id}/" in r.text
    assert "https://upstream" not in r.text
    assert "720p" in r.text
