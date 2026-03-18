"""Stream URL extraction for MostraGuarda via SuperVideo.

MostraGuarda embeds films via SuperVideo (or occasionally other players).
This module resolves the HLS master playlist URL by delegating to the
:mod:`streamload.player.supervideo` extractor.
"""

from __future__ import annotations

from streamload.core.exceptions import ServiceError
from streamload.models.stream import StreamBundle
from streamload.player import supervideo
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "mostraguarda"


def extract_streams(
    http: HttpClient,
    player_url: str,
) -> StreamBundle:
    """Resolve available streams for a MostraGuarda film.

    Parameters
    ----------
    http:
        Shared HTTP client.
    player_url:
        SuperVideo embed URL.

    Returns
    -------
    StreamBundle
        A bundle whose ``manifest_url`` is the HLS master playlist.

    Raises
    ------
    ServiceError
        When no playable stream can be resolved.
    """
    log.info("Extracting streams from MostraGuarda player: %s", player_url)

    playlist = supervideo.extract_playlist(http, player_url)
    if playlist is None:
        raise ServiceError(
            f"Could not resolve a playable stream from {player_url}",
            service_name=_SERVICE_TAG,
        )

    log.info("Resolved HLS playlist: %s", playlist)
    return StreamBundle(manifest_url=playlist)
