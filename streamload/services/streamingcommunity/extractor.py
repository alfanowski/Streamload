"""Stream URL extraction for StreamingCommunity via VixCloud.

Orchestrates the VixCloud player module to resolve HLS master playlist
URLs, fetches the manifest to enumerate tracks, and wraps everything in
a :class:`~streamload.models.stream.StreamBundle`.

Quality strategy ("opportunistic FHD"):

    The VixCloud embed page advertises ``window.canPlayFHD`` for each
    title. We don't fully trust this flag because it has been observed
    to be ``false`` even for titles that DO have a 1080p variant on the
    server. Therefore we always *try* the FHD playlist first; if it
    returns HTTP 403 or an empty playlist we fall back to the
    non-FHD URL gracefully. The cost is one extra HTTP probe when FHD
    is genuinely unavailable; the benefit is that we never miss 1080p
    when it is silently present.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from streamload.core.exceptions import ServiceError
from streamload.core.manifest.m3u8 import M3U8Parser
from streamload.models.stream import StreamBundle
from streamload.player import vixcloud
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "streamingcommunity"

# VixCloud requires same-origin referer for playlist requests.
_VIXCLOUD_REFERER = "https://vixcloud.co/"


def _with_fhd(url: str) -> str:
    """Return *url* with the ``h=1`` query param added (idempotent)."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    qs["h"] = ["1"]
    new_query = urlencode([(k, v[0]) for k, v in qs.items()])
    return urlunparse(parsed._replace(query=new_query))


def _without_fhd(url: str) -> str:
    """Return *url* with the ``h=1`` query param stripped (idempotent)."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    qs.pop("h", None)
    new_query = urlencode([(k, v[0]) for k, v in qs.items()])
    return urlunparse(parsed._replace(query=new_query))


def _fetch_master_playlist(http: HttpClient, url: str) -> StreamBundle | None:
    """Fetch *url* and parse it as an HLS master playlist.

    Returns ``None`` on HTTP error or empty/invalid playlist (caller
    decides whether to fall back to a different URL).
    """
    try:
        resp = http.get(url, headers={"Referer": _VIXCLOUD_REFERER})
    except Exception:
        log.debug("Master playlist fetch failed for %s", url, exc_info=True)
        return None
    if getattr(resp, "status_code", 0) != 200:
        log.debug("Master playlist returned HTTP %s for %s", resp.status_code, url)
        return None
    text = getattr(resp, "text", "") or ""
    if not text.strip():
        return None
    bundle = M3U8Parser().parse_master(text, url)
    if not bundle.video:
        return None
    return bundle


def extract_streams(
    http: HttpClient,
    base_url: str,
    media_id: int,
    *,
    episode_id: int | None = None,
) -> StreamBundle:
    """Resolve available streams for a title or episode.

    1. Walk the iframe -> VixCloud embed -> authenticated m3u8 chain.
    2. **Opportunistically** fetch the master m3u8 with ``h=1`` first;
       on 403 or empty playlist, retry without ``h=1``.
    3. Parse the playlist to enumerate video/audio/subtitle tracks.
    """
    content_label = (
        f"episode {episode_id} of title {media_id}"
        if episode_id is not None
        else f"title {media_id}"
    )
    log.info("Extracting streams for %s", content_label)

    base_playlist_url = vixcloud.extract_playlist(
        http,
        base_url,
        media_id,
        episode_id=episode_id,
    )

    if base_playlist_url is None:
        raise ServiceError(
            f"Could not resolve a playable stream for {content_label}",
            service_name=_SERVICE_TAG,
        )

    log.info("Resolved master playlist for %s: %s", content_label, base_playlist_url)

    # Opportunistic FHD: always try with h=1 first. If the server rejects
    # it (403) or returns an empty playlist, fall back to the no-h=1 URL.
    fhd_url = _with_fhd(base_playlist_url)
    fallback_url = _without_fhd(base_playlist_url)

    bundle = _fetch_master_playlist(http, fhd_url)
    chosen_url = fhd_url
    if bundle is None:
        log.info("FHD playlist unavailable for %s, falling back to non-FHD", content_label)
        bundle = _fetch_master_playlist(http, fallback_url)
        chosen_url = fallback_url

    if bundle is None:
        raise ServiceError(
            f"Master playlist returned no playable variants for {content_label}",
            service_name=_SERVICE_TAG,
        )

    # Carry over the manifest URL and required headers for segment downloads.
    bundle.manifest_url = chosen_url
    bundle.extra_headers = {"Referer": _VIXCLOUD_REFERER}

    log.info(
        "Parsed tracks for %s: %d video, %d audio, %d subtitle",
        content_label,
        len(bundle.video),
        len(bundle.audio),
        len(bundle.subtitles),
    )

    return bundle


def has_fhd_variant(bundle: StreamBundle) -> bool:
    """Return True if *bundle* contains a video stream at 1080p or higher."""
    for v in bundle.video:
        height = getattr(v, "height", None)
        if height is None:
            res = getattr(v, "resolution", "") or ""
            # resolution like "1920x1080" -> height = 1080
            if "x" in res:
                try:
                    height = int(res.split("x")[1])
                except (ValueError, IndexError):
                    height = None
        if height is not None and height >= 1080:
            return True
    return False
