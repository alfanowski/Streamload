"""Stream URL extraction for GuardaSerie via SuperVideo.

GuardaSerie embeds episodes via SuperVideo (or occasionally Dropload)
players.  This module resolves the HLS master playlist URL by
delegating to the :mod:`streamload.player.supervideo` extractor.
"""

from __future__ import annotations

from streamload.core.exceptions import ServiceError
from streamload.models.stream import StreamBundle
from streamload.player import supervideo
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "guardaserie"


def extract_streams(
    http: HttpClient,
    player_url: str,
    *,
    fallback_url: str | None = None,
) -> StreamBundle:
    """Resolve available streams for a GuardaSerie episode.

    Attempts the primary ``player_url`` first; if that fails and a
    ``fallback_url`` is available, tries the fallback.

    Parameters
    ----------
    http:
        Shared HTTP client.
    player_url:
        Primary player embed URL (typically SuperVideo).
    fallback_url:
        Optional fallback player URL (e.g. Dropload mirror).

    Returns
    -------
    StreamBundle
        A bundle whose ``manifest_url`` is the HLS master playlist.

    Raises
    ------
    ServiceError
        When no playable stream can be resolved from any player.
    """
    # Normalise URL scheme.
    if player_url.startswith("//"):
        player_url = "https:" + player_url

    log.info("Extracting streams from primary player: %s", player_url)
    playlist = supervideo.extract_playlist(http, player_url)

    if playlist:
        log.info("Resolved HLS playlist: %s", playlist)
        return StreamBundle(manifest_url=playlist)

    # Try fallback if available.
    if fallback_url:
        if fallback_url.startswith("//"):
            fallback_url = "https:" + fallback_url

        log.info("Primary player failed, trying fallback: %s", fallback_url)
        playlist = supervideo.extract_playlist(http, fallback_url)
        if playlist:
            log.info("Resolved HLS playlist from fallback: %s", playlist)
            return StreamBundle(manifest_url=playlist)

    raise ServiceError(
        f"Could not resolve a playable stream from {player_url}",
        service_name=_SERVICE_TAG,
    )
