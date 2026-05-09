"""Tests for the playback orchestrator."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from streamload.streaming.service import build_playback_session


@pytest.mark.asyncio
async def test_build_session_for_non_drm_movie():
    bundle = MagicMock()
    bundle.manifest_url = "https://upstream/master.m3u8"
    bundle.extra_headers = {"Referer": "https://upstream"}
    bundle.is_drm = False
    bundle.drm_keys = None
    bundle.subtitles = []

    fake_service = MagicMock()
    fake_service.short_name = "sc"
    fake_service.get_streams_async = AsyncMock(return_value=bundle)

    sess = await build_playback_session(
        user_id=uuid.uuid4(), tmdb_id=42, service=fake_service, media_id="m1",
    )
    assert sess.is_drm is False
    assert sess.upstream_master_url.startswith("https://upstream")


@pytest.mark.asyncio
async def test_build_session_for_drm_keeps_keys():
    bundle = MagicMock()
    bundle.manifest_url = "https://upstream/master.m3u8"
    bundle.extra_headers = {}
    bundle.is_drm = True
    bundle.drm_keys = [{"kid": "x", "key": "y"}]

    fake_service = MagicMock()
    fake_service.short_name = "rp"
    fake_service.get_streams_async = AsyncMock(return_value=bundle)

    sess = await build_playback_session(
        user_id=uuid.uuid4(), tmdb_id=42, service=fake_service, media_id="m1",
    )
    assert sess.is_drm is True
    assert sess.drm_keys == [{"kid": "x", "key": "y"}]
