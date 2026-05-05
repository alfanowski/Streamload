"""Regression tests for the VixCloud player script parser.

Captures the active-server-URL bug: VixCloud's embed page lists multiple
mirror servers in ``window.streams`` and the URL of the *active* one
carries a discriminator query param (``ab=1`` / ``ub=1`` / ...). The
playlist endpoint returns HTTP 403 if that param is missing.
"""
from __future__ import annotations

from streamload.player.vixcloud import (
    _parse_player_script,
    _select_active_stream_url,
    build_playlist_url,
)


SCRIPT_MULTI_SERVER = """
    window.video = { id: '199704', filename: '' };
    window.streams = [
        {"name":"Server1","active":false,"url":"https://vixcloud.co/playlist/199704?b=1&ub=1"},
        {"name":"Server2","active":1,"url":"https://vixcloud.co/playlist/199704?b=1&ab=1"}
    ];
    window.masterPlaylist = {
        params: {
            'token': 'd59854219ff06d7c4f81e5b96c495888',
            'expires': '1783194835',
            'asn': '',
        },
        url: 'https://vixcloud.co/playlist/199704?b=1',
    };
    window.canPlayFHD = false
"""

SCRIPT_LEGACY_NO_STREAMS = """
    window.video = { id: '12345' };
    window.masterPlaylist = {
        params: { 'token': 'abc', 'expires': '999' },
        url: 'https://vixcloud.co/playlist/12345?b=1',
    };
    window.canPlayFHD = true;
"""

SCRIPT_FHD_NUMERIC = """
    window.streams = [{"name":"S1","active":1,"url":"https://x.tld/p/1?b=1&ab=1"}];
    window.masterPlaylist = { params: { token:'t', expires:'e' }, url:'https://x.tld/p/1' };
    window.canPlayFHD = 1
"""


def test_select_active_stream_picks_entry_with_active_truthy():
    url = _select_active_stream_url(SCRIPT_MULTI_SERVER)
    assert url == "https://vixcloud.co/playlist/199704?b=1&ab=1"


def test_select_active_stream_returns_none_when_no_streams_array():
    assert _select_active_stream_url("no streams here") is None


def test_select_active_stream_falls_back_to_first_with_url_when_none_active():
    script = """
        window.streams = [
            {"name":"S1","active":false,"url":"https://a.tld/p?ab=1"},
            {"name":"S2","active":false,"url":"https://b.tld/p?ub=1"}
        ];
    """
    assert _select_active_stream_url(script) == "https://a.tld/p?ab=1"


def test_parse_prefers_active_stream_url_over_masterplaylist():
    """The active server URL with ``ab=1`` must win over masterPlaylist.url."""
    p = _parse_player_script(SCRIPT_MULTI_SERVER)
    assert p.master_url == "https://vixcloud.co/playlist/199704?b=1&ab=1"
    assert p.token == "d59854219ff06d7c4f81e5b96c495888"
    assert p.expires == "1783194835"
    assert p.can_play_fhd is False


def test_parse_falls_back_to_masterplaylist_when_no_streams():
    p = _parse_player_script(SCRIPT_LEGACY_NO_STREAMS)
    assert p.master_url == "https://vixcloud.co/playlist/12345?b=1"
    assert p.can_play_fhd is True


def test_parse_accepts_numeric_canplayfhd():
    p = _parse_player_script(SCRIPT_FHD_NUMERIC)
    assert p.can_play_fhd is True


def test_build_url_preserves_ab_discriminator():
    """The ``ab=1`` param must survive into the final URL -- omitting it
    causes VixCloud to return HTTP 403."""
    p = _parse_player_script(SCRIPT_MULTI_SERVER)
    final = build_playlist_url(p)
    assert final is not None
    assert "ab=1" in final
    assert "b=1" in final
    assert "token=d59854219ff06d7c4f81e5b96c495888" in final
    assert "expires=1783194835" in final


def test_build_url_omits_h_when_not_fhd():
    """canPlayFHD=false -> the playlist must not request 1080p variants."""
    p = _parse_player_script(SCRIPT_MULTI_SERVER)
    final = build_playlist_url(p)
    assert "h=1" not in final


def test_build_url_adds_h_when_fhd_supported():
    p = _parse_player_script(SCRIPT_LEGACY_NO_STREAMS)
    final = build_playlist_url(p)
    assert "h=1" in final


def test_build_url_returns_none_when_master_missing():
    from streamload.player.vixcloud import PlayerParams
    assert build_playlist_url(PlayerParams()) is None
