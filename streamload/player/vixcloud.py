"""VixCloud player extractor for Streamload.

Handles extraction of authenticated HLS master playlist URLs from the
VixCloud video player, which is used by StreamingCommunity and related
Italian streaming services.

The flow:
    1. Fetch the ``/iframe/{media_id}`` page from the service.
    2. Parse the ``<iframe>`` tag to get the VixCloud embed URL.
    3. Fetch the VixCloud embed page and extract the inline ``<script>``
       containing ``window.masterPlaylist``, ``window.video``, and auth
       parameters (token, expires).
    4. Build the final authenticated m3u8 master playlist URL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "vixcloud"


@dataclass
class PlayerParams:
    """Parsed parameters from the VixCloud player script."""

    master_url: str | None = None
    token: str | None = None
    expires: str | None = None
    video_id: int | None = None
    can_play_fhd: bool = False


def _parse_player_script(script_text: str) -> PlayerParams:
    """Extract player parameters from the inline ``<script>`` block.

    The script embeds variables such as::

        window.masterPlaylist = { ... url: 'https://...m3u8', ... };
        window.video = { id: '12345' };
        window.canPlayFHD = true;

    Returns a populated :class:`PlayerParams` dataclass.  Missing fields
    are left as ``None`` / ``False``.
    """
    params = PlayerParams()

    # -- token / expires / master playlist URL ------------------------------
    token_m = re.search(
        r"""(?:['"]token['"]|token)\s*:\s*['"](?P<token>[^'"]+)['"]""",
        script_text,
    )
    expires_m = re.search(
        r"""(?:['"]expires['"]|expires)\s*:\s*['"](?P<expires>[^'"]+)['"]""",
        script_text,
    )
    url_m = re.search(
        r"""(?:['"]url['"]|url)\s*:\s*['"](?P<url>https?://[^'"]+)['"]""",
        script_text,
    )

    # -- video id and FHD capability ----------------------------------------
    video_id_m = re.search(
        r"""window\.video\s*=\s*\{[^}]*\bid\s*:\s*['"](?P<id>\d+)['"]""",
        script_text,
    )
    canplay_m = re.search(
        r"window\.canPlayFHD\s*=\s*(true|false)",
        script_text,
    )

    params.token = token_m.group("token") if token_m else None
    params.expires = expires_m.group("expires") if expires_m else None
    params.master_url = url_m.group("url") if url_m else None
    params.video_id = int(video_id_m.group("id")) if video_id_m else None
    params.can_play_fhd = bool(canplay_m and canplay_m.group(1) == "true")

    return params


def get_iframe_url(
    http: HttpClient,
    base_url: str,
    media_id: int,
    *,
    episode_id: int | None = None,
) -> str:
    """Fetch the ``/iframe/{media_id}`` page and extract the embed URL.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        Service base URL, e.g. ``"https://streamingcommunity.prof/it"``.
    media_id:
        The service-internal numeric ID of the title.
    episode_id:
        If provided the request targets a specific episode (series mode).
        When ``None`` the request targets a film.

    Returns
    -------
    str
        The ``src`` attribute of the ``<iframe>`` tag pointing to the
        VixCloud embed page.

    Raises
    ------
    ServiceError
        When the page cannot be fetched or the iframe is missing.
    """
    params: dict[str, str] = {}
    if episode_id is not None:
        params["episode_id"] = str(episode_id)
        params["next_episode"] = "1"

    url = f"{base_url}/iframe/{media_id}"
    log.debug("Fetching iframe page: %s  params=%s", url, params)

    resp = http.get(url, params=params or None, use_curl=True)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    iframe = soup.find("iframe")
    if iframe is None or not iframe.get("src"):
        raise ServiceError(
            f"No iframe found on {url}",
            service_name=_SERVICE_TAG,
        )

    iframe_src: str = iframe["src"]
    log.debug("Extracted iframe src: %s", iframe_src)
    return iframe_src


def get_player_params(http: HttpClient, iframe_url: str) -> PlayerParams:
    """Fetch the VixCloud embed page and parse player parameters.

    Parameters
    ----------
    http:
        Shared HTTP client.
    iframe_url:
        The full VixCloud embed URL (``https://vixcloud.co/embed/...``).

    Returns
    -------
    PlayerParams
        Parsed player data including the raw master playlist URL, auth
        token, expiry, and FHD flag.
    """
    log.debug("Fetching VixCloud player page: %s", iframe_url)
    resp = http.get(iframe_url)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    body = soup.find("body")
    if body is None:
        raise ServiceError(
            f"No <body> in VixCloud player page: {iframe_url}",
            service_name=_SERVICE_TAG,
        )

    script_tag = body.find("script")
    if script_tag is None or not script_tag.string:
        raise ServiceError(
            f"No inline script in VixCloud player page: {iframe_url}",
            service_name=_SERVICE_TAG,
        )

    params = _parse_player_script(script_tag.string)
    log.debug(
        "Parsed player params: url=%s  token=%s  expires=%s  fhd=%s",
        params.master_url,
        params.token is not None,
        params.expires is not None,
        params.can_play_fhd,
    )
    return params


def build_playlist_url(params: PlayerParams) -> str | None:
    """Construct the final authenticated m3u8 master playlist URL.

    Appends authentication query parameters (``token``, ``expires``) and
    the FHD flag (``h=1``) when applicable.

    Parameters
    ----------
    params:
        Player parameters as returned by :func:`get_player_params`.

    Returns
    -------
    str | None
        The fully-qualified playlist URL, or ``None`` if the player
        params do not contain a usable URL.
    """
    if not params.master_url:
        return None

    parsed = urlparse(params.master_url)
    query_params: dict[str, str] = {}

    # Preserve any existing 'b' param (bandwidth hint).
    existing_qs = parse_qs(parsed.query)
    if existing_qs.get("b") == ["1"]:
        query_params["b"] = "1"

    # Always request FHD. If the server doesn't support it, the playlist
    # will simply not include 1080p variants (graceful fallback).
    query_params["h"] = "1"

    # Authentication.
    if params.token:
        query_params["token"] = params.token
    if params.expires:
        query_params["expires"] = params.expires

    final_url = urlunparse(parsed._replace(query=urlencode(query_params)))
    log.debug("Built playlist URL: %s", final_url)
    return final_url


def extract_playlist(
    http: HttpClient,
    base_url: str,
    media_id: int,
    *,
    episode_id: int | None = None,
) -> str | None:
    """End-to-end convenience: iframe -> player page -> authenticated m3u8.

    Combines :func:`get_iframe_url`, :func:`get_player_params`, and
    :func:`build_playlist_url` into a single call.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        Service base URL including language prefix.
    media_id:
        Service-internal numeric title ID.
    episode_id:
        Episode ID for series; ``None`` for films.

    Returns
    -------
    str | None
        The authenticated master playlist URL, or ``None`` when the
        player does not expose a valid stream.
    """
    iframe_url = get_iframe_url(http, base_url, media_id, episode_id=episode_id)
    params = get_player_params(http, iframe_url)
    return build_playlist_url(params)
