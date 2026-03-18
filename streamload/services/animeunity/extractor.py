"""Stream URL extraction for AnimeUnity via VixCloud.

AnimeUnity uses the same VixCloud player infrastructure as
StreamingCommunity.  This module orchestrates the VixCloud player module
to resolve HLS master playlist URLs and wraps the result in a
:class:`~streamload.models.stream.StreamBundle`.
"""

from __future__ import annotations

from streamload.core.exceptions import ServiceError
from streamload.models.stream import StreamBundle
from streamload.player import vixcloud
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "animeunity"


def extract_streams(
    http: HttpClient,
    base_url: str,
    media_id: int,
    *,
    episode_id: int | None = None,
) -> StreamBundle:
    """Resolve available streams for an anime title or episode.

    Delegates to :func:`streamload.player.vixcloud.extract_playlist` to
    walk the iframe -> VixCloud embed -> m3u8 chain, then wraps the
    result in a :class:`StreamBundle`.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        Service base URL, e.g. ``"https://animeunity.so"``.
    media_id:
        AnimeUnity internal anime ID.
    episode_id:
        Episode ID for series content.  ``None`` for single-episode
        anime (movies, OVAs).

    Returns
    -------
    StreamBundle
        A bundle whose ``manifest_url`` is the authenticated HLS master
        playlist.

    Raises
    ------
    ServiceError
        When no playable stream can be resolved.
    """
    content_label = (
        f"episode {episode_id} of anime {media_id}"
        if episode_id is not None
        else f"anime {media_id}"
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
    return StreamBundle(manifest_url=playlist_url)
