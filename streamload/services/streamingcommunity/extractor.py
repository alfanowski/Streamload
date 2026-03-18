"""Stream URL extraction for StreamingCommunity via VixCloud.

Orchestrates the VixCloud player module to resolve HLS master playlist
URLs, fetches the manifest to enumerate tracks, and wraps everything in
a :class:`~streamload.models.stream.StreamBundle`.
"""

from __future__ import annotations

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


def extract_streams(
    http: HttpClient,
    base_url: str,
    media_id: int,
    *,
    episode_id: int | None = None,
) -> StreamBundle:
    """Resolve available streams for a title or episode.

    1. Walk the iframe -> VixCloud embed -> authenticated m3u8 chain.
    2. Fetch the master m3u8 with the correct VixCloud referer.
    3. Parse it to enumerate video/audio/subtitle tracks.

    Returns a fully-populated :class:`StreamBundle`.
    """
    content_label = (
        f"episode {episode_id} of title {media_id}"
        if episode_id is not None
        else f"title {media_id}"
    )
    log.info("Extracting streams for %s", content_label)

    playlist_url = vixcloud.extract_playlist(
        http,
        base_url,
        media_id,
        episode_id=episode_id,
    )

    if playlist_url is None:
        raise ServiceError(
            f"Could not resolve a playable stream for {content_label}",
            service_name=_SERVICE_TAG,
        )

    log.info("Resolved master playlist for %s: %s", content_label, playlist_url)

    # Fetch the master m3u8 -- VixCloud requires same-origin referer.
    resp = http.get(playlist_url, headers={"Referer": _VIXCLOUD_REFERER})
    resp.raise_for_status()

    # Parse the master playlist to extract all tracks.
    parser = M3U8Parser()
    bundle = parser.parse_master(resp.text, playlist_url)

    # Carry over the manifest URL and required headers for segment downloads.
    bundle.manifest_url = playlist_url
    bundle.extra_headers = {"Referer": _VIXCLOUD_REFERER}

    log.info(
        "Parsed tracks for %s: %d video, %d audio, %d subtitle",
        content_label,
        len(bundle.video),
        len(bundle.audio),
        len(bundle.subtitles),
    )

    return bundle
