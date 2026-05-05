"""Tests for opportunistic FHD + multi-mirror upgrade in StreamingCommunity.

Covers:
    * has_fhd_variant detection on different VideoTrack shapes.
    * _with_fhd / _without_fhd URL helpers (idempotent + non-destructive).
    * extract_streams falls back when h=1 returns 403 / empty / non-200.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from streamload.models.stream import StreamBundle, VideoTrack
from streamload.services.streamingcommunity.extractor import (
    _with_fhd,
    _without_fhd,
    extract_streams,
    has_fhd_variant,
)


# -- URL helpers --------------------------------------------------------

def test_with_fhd_adds_h_param():
    assert "h=1" in _with_fhd("https://x.tld/p/1?b=1&ab=1")


def test_with_fhd_idempotent_when_already_set():
    out = _with_fhd("https://x.tld/p/1?h=1&b=1")
    assert out.count("h=1") == 1


def test_with_fhd_preserves_other_params():
    out = _with_fhd("https://x.tld/p/1?b=1&ab=1&token=t&expires=e")
    assert "b=1" in out and "ab=1" in out
    assert "token=t" in out and "expires=e" in out


def test_without_fhd_strips_h_param():
    assert "h=1" not in _without_fhd("https://x.tld/p/1?b=1&h=1&ab=1")


def test_without_fhd_idempotent_when_absent():
    assert _without_fhd("https://x.tld/p/1?b=1") == "https://x.tld/p/1?b=1"


def test_without_fhd_preserves_other_params():
    out = _without_fhd("https://x.tld/p/1?b=1&h=1&ab=1&token=t")
    assert "b=1" in out and "ab=1" in out and "token=t" in out


# -- has_fhd_variant ----------------------------------------------------

def _make_bundle(*resolutions: str) -> StreamBundle:
    bundle = StreamBundle()
    for r in resolutions:
        bundle.video.append(VideoTrack(id=r, resolution=r, codec="h264"))
    return bundle


def test_has_fhd_true_for_1920x1080():
    assert has_fhd_variant(_make_bundle("1920x1080")) is True


def test_has_fhd_true_for_3840x2160():
    assert has_fhd_variant(_make_bundle("3840x2160")) is True


def test_has_fhd_false_for_720p_only():
    assert has_fhd_variant(_make_bundle("854x480", "1280x720")) is False


def test_has_fhd_false_for_empty_bundle():
    assert has_fhd_variant(_make_bundle()) is False


# -- extract_streams fallback behaviour ---------------------------------

# A minimal HLS master playlist with a single 720p variant.
_MASTER_720P = (
    "#EXTM3U\n"
    '#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720\n'
    "https://x.tld/720p.m3u8\n"
)
# Same shape but at 1080p.
_MASTER_1080P = (
    "#EXTM3U\n"
    '#EXT-X-STREAM-INF:BANDWIDTH=4500000,RESOLUTION=1920x1080\n'
    "https://x.tld/1080p.m3u8\n"
)


def _resp(status: int, text: str):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


@patch("streamload.services.streamingcommunity.extractor.vixcloud.extract_playlist")
def test_extract_uses_fhd_when_available(mock_extract):
    mock_extract.return_value = "https://vixcloud.co/p/1?b=1&ab=1&token=t&expires=e"
    http = MagicMock()
    # First call (with h=1) succeeds -> 1080p bundle
    http.get.return_value = _resp(200, _MASTER_1080P)

    bundle = extract_streams(http, "https://sc.tld/it", 1)

    assert "h=1" in bundle.manifest_url
    assert has_fhd_variant(bundle) is True


@patch("streamload.services.streamingcommunity.extractor.vixcloud.extract_playlist")
def test_extract_falls_back_when_fhd_returns_403(mock_extract):
    mock_extract.return_value = "https://vixcloud.co/p/1?b=1&ab=1&token=t&expires=e"
    http = MagicMock()
    # First call (with h=1) returns 403; second call (without) returns 720p
    http.get.side_effect = [
        _resp(403, "Forbidden"),
        _resp(200, _MASTER_720P),
    ]

    bundle = extract_streams(http, "https://sc.tld/it", 1)

    assert "h=1" not in bundle.manifest_url
    assert has_fhd_variant(bundle) is False
    assert len(bundle.video) == 1
    assert http.get.call_count == 2


@patch("streamload.services.streamingcommunity.extractor.vixcloud.extract_playlist")
def test_extract_falls_back_when_fhd_returns_empty(mock_extract):
    mock_extract.return_value = "https://vixcloud.co/p/1?b=1&ab=1&token=t&expires=e"
    http = MagicMock()
    # FHD attempt: 200 but empty playlist -> fallback wins
    http.get.side_effect = [
        _resp(200, "#EXTM3U\n"),  # no variants
        _resp(200, _MASTER_720P),
    ]

    bundle = extract_streams(http, "https://sc.tld/it", 1)

    assert has_fhd_variant(bundle) is False
    assert len(bundle.video) == 1


@patch("streamload.services.streamingcommunity.extractor.vixcloud.extract_playlist")
def test_extract_raises_when_both_attempts_fail(mock_extract):
    from streamload.core.exceptions import ServiceError

    mock_extract.return_value = "https://vixcloud.co/p/1?b=1&token=t&expires=e"
    http = MagicMock()
    http.get.side_effect = [_resp(403, ""), _resp(403, "")]

    with pytest.raises(ServiceError, match="no playable variants"):
        extract_streams(http, "https://sc.tld/it", 1)
