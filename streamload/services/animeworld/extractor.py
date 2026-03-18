"""Stream URL extraction for AnimeWorld via SweetPixel.

AnimeWorld uses its own download API (the SweetPixel player) which
returns direct MP4 download links.  This module orchestrates the
SweetPixel player module and wraps the result in a
:class:`~streamload.models.stream.StreamBundle`.
"""

from __future__ import annotations

from streamload.core.exceptions import ServiceError
from streamload.models.stream import StreamBundle
from streamload.player import sweetpixel
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "animeworld"


def extract_streams(
    http: HttpClient,
    base_url: str,
    episode_id: str,
    session_id: str,
    csrf_token: str,
) -> StreamBundle:
    """Resolve the MP4 download URL for an AnimeWorld episode.

    Delegates to :func:`streamload.player.sweetpixel.extract_download_url`
    to call the AnimeWorld download API and extract the direct link.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        Service base URL, e.g. ``"https://www.animeworld.it"``.
    episode_id:
        The episode ID used in the download API path.
    session_id:
        AnimeWorld session cookie.
    csrf_token:
        CSRF token for API calls.

    Returns
    -------
    StreamBundle
        A bundle whose ``manifest_url`` is the direct MP4 download link.

    Raises
    ------
    ServiceError
        When no download URL can be resolved.
    """
    log.info("Extracting streams for AnimeWorld episode %s", episode_id)

    mp4_url = sweetpixel.extract_download_url(
        http,
        base_url,
        episode_id,
        session_id,
        csrf_token,
    )

    if mp4_url is None:
        raise ServiceError(
            f"Could not resolve a download URL for episode {episode_id}",
            service_name=_SERVICE_TAG,
        )

    log.info("Resolved MP4 URL for episode %s: %s", episode_id, mp4_url)
    return StreamBundle(manifest_url=mp4_url)
