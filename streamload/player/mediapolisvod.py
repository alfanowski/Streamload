"""MediaPolisVod player extractor for Streamload.

Handles extraction of stream URLs from the RaiPlay platform via the
MediaPolis VOD relinker service.

The flow:
    1. Receive a RaiPlay video page URL (ending in ``.html`` or with
       ``/video/`` path).
    2. Fetch the corresponding ``.json`` descriptor to obtain the
       ``content_url`` containing the relinker element key.
    3. Call the relinker servlet with ``output=62`` to obtain the final
       streaming URL (HLS m3u8 or DASH mpd) and optional DRM licence
       info.

The relinker response (``output=62``) is a JSON object with::

    {
        "video": ["https://...m3u8_or_mpd_url"],
        "licence_server_map": {
            "drmLicenseUrlValues": [{"licenceUrl": "https://..."}]
        }
    }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "mediapolisvod"

_RELINKER_URL = "https://mediapolisvod.rai.it/relinker/relinkerServlet.htm"


@dataclass
class RelinkerResult:
    """Parsed output from the MediaPolis VOD relinker servlet."""

    stream_url: str | None = None
    license_url: str | None = None
    is_drm: bool = False


def _extract_element_key(content_url: str) -> str | None:
    """Extract the element key from a RaiPlay ``content_url``.

    The content URL looks like::

        /relinker/relinkerServlet.htm?cont=ELEMENT_KEY

    Returns the element key, or ``None`` if not parseable.
    """
    if "=" not in content_url:
        return None
    return content_url.split("=", 1)[1].strip()


def _fetch_video_json(http: HttpClient, video_url: str) -> dict:
    """Fetch the ``.json`` descriptor for a RaiPlay video page.

    Parameters
    ----------
    http:
        Shared HTTP client.
    video_url:
        A RaiPlay video page URL.  If it does not already end with
        ``.json``, the function attempts to build the JSON URL from the
        video path.

    Returns
    -------
    dict
        The parsed JSON descriptor.

    Raises
    ------
    ServiceError
        When the JSON cannot be fetched or parsed.
    """
    json_url = video_url
    if not json_url.endswith(".json"):
        if "/video/" in json_url:
            # Strip .html or trailing slashes, append .json
            json_url = re.sub(r"\.html?$", "", json_url.rstrip("/"))
            json_url += ".json"
        else:
            raise ServiceError(
                f"Cannot determine JSON URL from: {video_url}",
                service_name=_SERVICE_TAG,
            )

    log.debug("Fetching video JSON: %s", json_url)
    resp = http.get(json_url)
    resp.raise_for_status()
    return resp.json()


def call_relinker(
    http: HttpClient,
    element_key: str,
) -> RelinkerResult:
    """Call the MediaPolis VOD relinker servlet.

    Parameters
    ----------
    http:
        Shared HTTP client.
    element_key:
        The content element key extracted from the video descriptor.

    Returns
    -------
    RelinkerResult
        The stream URL and optional DRM licence URL.

    Raises
    ------
    ServiceError
        When the relinker fails or returns no video URL.
    """
    params = {
        "cont": element_key,
        "output": "62",
    }

    log.debug("Calling relinker with key=%s", element_key)
    resp = http.get(_RELINKER_URL, params=params)
    resp.raise_for_status()

    # The relinker may return latin-1 encoded JSON.
    try:
        data = resp.json()
    except Exception:
        try:
            data = json.loads(resp.content.decode("latin-1"))
        except Exception as exc:
            raise ServiceError(
                f"Failed to decode relinker response: {exc}",
                service_name=_SERVICE_TAG,
            ) from exc

    result = RelinkerResult()

    # Extract stream URL.
    video_list = data.get("video")
    if isinstance(video_list, list) and video_list:
        result.stream_url = video_list[0]
    elif isinstance(video_list, str):
        result.stream_url = video_list

    # Extract DRM licence URL if present.
    licence_map = data.get("licence_server_map")
    if isinstance(licence_map, dict):
        drm_values = licence_map.get("drmLicenseUrlValues")
        if isinstance(drm_values, list) and drm_values:
            licence_url = drm_values[0].get("licenceUrl")
            if licence_url:
                result.license_url = licence_url
                result.is_drm = True

    log.debug(
        "Relinker result: stream=%s  drm=%s  license=%s",
        result.stream_url is not None,
        result.is_drm,
        result.license_url is not None,
    )
    return result


def extract_stream_url(
    http: HttpClient,
    video_url: str,
) -> RelinkerResult:
    """End-to-end convenience: video page URL -> relinker -> stream URL.

    Combines :func:`_fetch_video_json` and :func:`call_relinker` into
    a single call.

    Parameters
    ----------
    http:
        Shared HTTP client.
    video_url:
        A RaiPlay video page URL or JSON descriptor URL.

    Returns
    -------
    RelinkerResult
        The resolved stream URL and optional DRM licence info.

    Raises
    ------
    ServiceError
        When any step in the chain fails.
    """
    video_data = _fetch_video_json(http, video_url)

    # Navigate to content_url: video_data.video.content_url
    video_obj = video_data.get("video")
    if not isinstance(video_obj, dict):
        raise ServiceError(
            f"No 'video' object in JSON descriptor for {video_url}",
            service_name=_SERVICE_TAG,
        )

    content_url = video_obj.get("content_url")
    if not content_url:
        raise ServiceError(
            f"No 'content_url' in video descriptor for {video_url}",
            service_name=_SERVICE_TAG,
        )

    element_key = _extract_element_key(content_url)
    if not element_key:
        raise ServiceError(
            f"Cannot extract element key from content_url: {content_url}",
            service_name=_SERVICE_TAG,
        )

    return call_relinker(http, element_key)


def generate_license_url(
    http: HttpClient,
    element_key: str,
) -> str | None:
    """Resolve the Widevine licence URL for a DRM-protected RaiPlay asset.

    Parameters
    ----------
    http:
        Shared HTTP client.
    element_key:
        The content element key (``mpd_id``).

    Returns
    -------
    str | None
        The licence server URL, or ``None`` if the asset is not DRM
        protected.
    """
    result = call_relinker(http, element_key)
    return result.license_url


def fix_manifest_url(manifest_url: str) -> str:
    """Fix RaiPlay HLS manifest URLs to include all standard quality levels.

    RaiPlay sometimes delivers manifests with a limited quality set.
    This function rewrites the quality specification in the URL to
    include the full range: 1200, 1800, 2400, 3600, 5000 kbps.

    Parameters
    ----------
    manifest_url:
        Original HLS manifest URL.

    Returns
    -------
    str
        The URL with the full quality specification, or the original
        URL if no quality pattern is found.
    """
    standard_qualities = "1200,1800,2400,3600,5000"
    pattern = r"(_,[\d,]+)(/playlist\.m3u8)"

    match = re.search(pattern, manifest_url)
    if match:
        return re.sub(pattern, f"_,{standard_qualities}\\2", manifest_url)

    return manifest_url
