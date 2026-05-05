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

import json
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


def _select_active_stream_url(script_text: str) -> str | None:
    """Pick the URL of the active server from ``window.streams``.

    The embed script declares an array of mirror servers::

        window.streams = [
            {"name":"Server1","active":false,"url":"https://.../playlist/X?b=1&ub=1"},
            {"name":"Server2","active":1,         "url":"https://.../playlist/X?b=1&ab=1"},
        ];

    Each server URL carries a discriminator query param (``ab=1``,
    ``ub=1``, …) that is **mandatory** for VixCloud to accept the request.
    The plain ``window.masterPlaylist.url`` does not include it and gets
    rejected with HTTP 403. We must use the ``url`` of the entry where
    ``active`` is truthy (``1`` or ``true``).
    """
    m = re.search(r"window\.streams\s*=\s*(\[.*?\])\s*;", script_text, re.DOTALL)
    if not m:
        return None
    try:
        streams = json.loads(m.group(1))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(streams, list):
        return None

    # Prefer the active server. Fall back to the first server with a URL.
    for s in streams:
        if isinstance(s, dict) and s.get("active") and s.get("url"):
            return str(s["url"])
    for s in streams:
        if isinstance(s, dict) and s.get("url"):
            return str(s["url"])
    return None


def _parse_player_script(script_text: str) -> PlayerParams:
    """Extract player parameters from the inline ``<script>`` block.

    The script embeds variables such as::

        window.streams = [{"name":"Server1","active":1,"url":"https://...?b=1&ab=1"}, ...];
        window.masterPlaylist = { params: { token:'…', expires:'…' }, url:'…' };
        window.video = { id: '12345' };
        window.canPlayFHD = true;

    The active-server URL from ``window.streams`` (when present) takes
    priority over ``window.masterPlaylist.url`` because it carries the
    server-discriminator query param VixCloud requires.
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
    # Accept ``true`` / ``false`` and also numeric ``1`` / ``0`` -- VixCloud
    # has been observed to use both forms across pages.
    canplay_m = re.search(
        r"window\.canPlayFHD\s*=\s*(true|false|1|0)\b",
        script_text,
    )

    params.token = token_m.group("token") if token_m else None
    params.expires = expires_m.group("expires") if expires_m else None
    # Prefer the active-server URL from ``window.streams`` (carries the
    # discriminator param VixCloud requires); fall back to masterPlaylist.url.
    active_url = _select_active_stream_url(script_text)
    params.master_url = active_url or (url_m.group("url") if url_m else None)
    params.video_id = int(video_id_m.group("id")) if video_id_m else None
    params.can_play_fhd = bool(canplay_m and canplay_m.group(1) in ("true", "1"))

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
    # Preserve every existing query param verbatim. The active-server URL
    # may carry mandatory discriminators (e.g. ``ab=1``, ``ub=1``) that
    # VixCloud uses to route the request -- stripping them yields HTTP 403.
    existing_qs = parse_qs(parsed.query)
    query_params: dict[str, str] = {k: v[0] for k, v in existing_qs.items() if v}

    # Request FHD only when the player advertises it; otherwise the server
    # may return an empty playlist or reject the request entirely.
    if params.can_play_fhd:
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
