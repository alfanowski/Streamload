"""Stream URL extraction for RaiPlay via MediaPolisVod.

Resolves streaming URLs for RaiPlay content through the MediaPolis VOD
relinker service.  Content may be:

- **Non-DRM (HLS)**: Direct m3u8 master playlist.
- **DRM (DASH)**: MPD manifest with Widevine protection and a
  separate licence URL.

The extractor wraps results in a :class:`~streamload.models.stream.StreamBundle`.
"""

from __future__ import annotations

import re

from streamload.core.exceptions import ServiceError
from streamload.models.stream import StreamBundle
from streamload.player import mediapolisvod
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "raiplay"
_BASE_URL = "https://www.raiplay.it"


def extract_streams_from_url(
    http: HttpClient,
    video_page_url: str,
    *,
    mpd_id: str = "",
) -> StreamBundle:
    """Resolve streams for a RaiPlay video page URL.

    Parameters
    ----------
    http:
        Shared HTTP client.
    video_page_url:
        Full URL to a RaiPlay video page (episode or film).
    mpd_id:
        The element key for DRM licence generation.  If empty, the
        extractor will attempt to extract it from the video descriptor.

    Returns
    -------
    StreamBundle
        A bundle with ``manifest_url`` and optional DRM metadata.

    Raises
    ------
    ServiceError
        When no playable stream can be resolved.
    """
    log.info("Extracting streams from: %s", video_page_url)

    result = mediapolisvod.extract_stream_url(http, video_page_url)

    if not result.stream_url:
        raise ServiceError(
            f"No stream URL resolved for {video_page_url}",
            service_name=_SERVICE_TAG,
        )

    manifest_url = result.stream_url

    # For HLS streams, fix the quality specification.
    if ".m3u8" in manifest_url:
        manifest_url = mediapolisvod.fix_manifest_url(manifest_url)

    bundle = StreamBundle(manifest_url=manifest_url)

    # DRM (DASH) path.
    if result.is_drm and result.license_url:
        bundle.drm_type = "widevine"
        bundle.license_url = result.license_url
        log.info("DRM stream (Widevine DASH): %s", manifest_url)

    # If content has mpd_id but relinker didn't return DRM info,
    # try to generate the licence URL explicitly.
    elif mpd_id and ".mpd" in manifest_url:
        license_url = mediapolisvod.generate_license_url(http, mpd_id)
        if license_url:
            bundle.drm_type = "widevine"
            bundle.license_url = license_url
            log.info("DRM stream (licence from mpd_id): %s", manifest_url)

    else:
        log.info("Non-DRM stream (HLS): %s", manifest_url)

    return bundle


def extract_streams_for_film(
    http: HttpClient,
    film_url: str,
) -> StreamBundle:
    """Resolve streams for a RaiPlay film.

    Films use a ``first_item_path`` from the title JSON to locate the
    video page, then delegate to :func:`extract_streams_from_url`.

    Parameters
    ----------
    http:
        Shared HTTP client.
    film_url:
        The RaiPlay page URL for the film.

    Returns
    -------
    StreamBundle
        Resolved stream bundle.
    """
    # Fetch the film's JSON descriptor to get first_item_path.
    json_url = film_url.rstrip("/")
    if not json_url.endswith(".json"):
        json_url += ".json"

    log.debug("Fetching film JSON: %s", json_url)
    resp = http.get(json_url)
    resp.raise_for_status()
    data = resp.json()

    first_item_path = data.get("first_item_path", "")
    if not first_item_path:
        raise ServiceError(
            f"No first_item_path in film descriptor: {json_url}",
            service_name=_SERVICE_TAG,
        )

    video_page_url = f"{_BASE_URL}{first_item_path}"
    return extract_streams_from_url(http, video_page_url)
