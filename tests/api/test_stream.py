"""HLS proxy endpoints tests."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from streamload.streaming.sessions import PlaybackSession, registry


@pytest.fixture
async def stream_session():
    """Create and register a PlaybackSession for testing."""
    sess = PlaybackSession.create(
        user_id=uuid.uuid4(),
        tmdb_id=42,
        service_short_name="sc",
        upstream_master_url="https://up/master.m3u8",
        upstream_headers={"Referer": "https://up"},
    )
    registry.put(sess)
    yield sess
    registry.remove(sess.id)


@pytest.mark.asyncio
async def test_master_returns_rewritten_playlist(api_client: httpx.AsyncClient, stream_session: PlaybackSession):
    upstream_text = (
        "#EXTM3U\n"
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="It",LANGUAGE="ita",URI="https://up/audio?token=x"\n'
        "#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720\n"
        "https://up/playlist?type=video&rendition=720p&token=x\n"
    )
    with patch("streamload.api.routes.stream._fetch_upstream_text", return_value=upstream_text):
        r = await api_client.get(f"/stream/{stream_session.id}/master.m3u8")
    assert r.status_code == 200
    assert "#EXTM3U" in r.text
    assert f"/stream/{stream_session.id}/" in r.text
    assert "https://up" not in r.text


@pytest.mark.asyncio
async def test_master_unknown_session_returns_404(api_client: httpx.AsyncClient):
    r = await api_client.get(f"/stream/{uuid.uuid4()}/master.m3u8")
    assert r.status_code == 404
