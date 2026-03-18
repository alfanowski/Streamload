"""Stream URL extraction for Mediaset Infinity.

Resolves DASH (MPD) stream URLs and Widevine DRM licence URLs for
Mediaset Infinity content.

The flow:
    1. Call the playback check API to get the ``mediaSelector``.
    2. Fetch the SMIL manifest from the media selector URL to get
       the MPD URL and tracking data.
    3. Generate the Widevine licence URL from the tracking data.
    4. Probe quality variants to find the best available MPD.
"""

from __future__ import annotations

import urllib.parse
from urllib.parse import urlparse, urlunparse

from streamload.core.exceptions import ServiceError
from streamload.models.stream import StreamBundle, SubtitleTrack
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

from .scraper import parse_smil_response

log = get_logger(__name__)

_SERVICE_TAG = "mediasetinfinity"
_PLAYBACK_CHECK_URL = (
    "https://api-ott-prod-fe.mediaset.net/PROD/play/playback/check/v2.0"
)
_LICENSE_BASE_URL = (
    "https://widevine.entitlement.theplatform.eu/wv/web/ModularDrm"
    "/getRawWidevineLicense"
)


def _get_playback_info(
    http: HttpClient,
    content_id: str,
    be_token: str,
) -> dict:
    """Call the Mediaset playback check API.

    Parameters
    ----------
    http:
        Shared HTTP client.
    content_id:
        The GUID of the content to play.
    be_token:
        Bearer token for authorization.

    Returns
    -------
    dict
        The ``mediaSelector`` object from the response.

    Raises
    ------
    ServiceError
        On playback errors (Infinity+ required, rental needed, etc.).
    """
    headers = {"authorization": f"Bearer {be_token}"}
    json_body = {
        "contentId": content_id,
        "streamType": "VOD",
    }

    log.debug("Playback check for content_id=%s", content_id)
    resp = http.post(_PLAYBACK_CHECK_URL, headers=headers, json=json_body)
    resp.raise_for_status()
    data = resp.json()

    # Check for known error codes.
    error = data.get("error")
    if isinstance(error, dict):
        code = error.get("code", "")
        error_map = {
            "PL022": "Infinity+ subscription required for this content.",
            "PL402": "Content available for rental: you must rent it first.",
            "PL053": "Content has no available purchasable rights.",
        }
        if code in error_map:
            raise ServiceError(error_map[code], service_name=_SERVICE_TAG)

    playback_json = data.get("response", {}).get("mediaSelector")
    if not playback_json:
        raise ServiceError(
            f"No mediaSelector in playback response for {content_id}",
            service_name=_SERVICE_TAG,
        )

    return playback_json


def _get_tracking_info(
    http: HttpClient,
    playback_json: dict,
    be_token: str,
    *,
    is_premium: bool = False,
) -> dict | None:
    """Fetch the SMIL manifest and extract video/subtitle info.

    Parameters
    ----------
    http:
        Shared HTTP client.
    playback_json:
        The ``mediaSelector`` object from the playback check.
    be_token:
        Bearer token.
    is_premium:
        Whether the user has a premium (Infinity+) subscription.

    Returns
    -------
    dict | None
        ``{"videos": [...], "subtitles": [...]}`` or ``None``.
    """
    if is_premium:
        qualities = ("HD", "HR", "SD", "SS")
    else:
        qualities = ("HR", "SD", "SS")

    parts: list[str] = []
    for q in qualities:
        parts.append(f"{q},browser,widevine,geoIT|geoNo")
        parts.append(f"{q},browser,geoIT|geoNo")
    asset_types = ":".join(parts)

    params: dict[str, str] = {
        "format": "SMIL",
        "auth": be_token,
        "formats": "MPEG-DASH",
        "assetTypes": asset_types,
        "balance": "true",
        "auto": "true",
        "tracking": "true",
        "delivery": "Streaming",
    }

    if "publicUrl" in playback_json:
        params["publicUrl"] = playback_json["publicUrl"]

    smil_url = playback_json.get("url", "")
    if not smil_url:
        log.error("No URL in mediaSelector")
        return None

    log.debug("Fetching SMIL manifest: %s", smil_url)

    try:
        resp = http.get(smil_url, params=params)
        resp.raise_for_status()
        return parse_smil_response(resp.text)
    except Exception:
        log.error("Failed to fetch/parse SMIL manifest", exc_info=True)
        return None


def _generate_license_url(
    tracking_info: dict,
    be_token: str,
    account_id: str,
) -> str:
    """Generate the Widevine licence URL from tracking data.

    Parameters
    ----------
    tracking_info:
        A single video entry from the SMIL parse result.
    be_token:
        Bearer token.
    account_id:
        The Mediaset account ID.

    Returns
    -------
    str
        The full licence URL with query parameters.
    """
    tracking_data = tracking_info.get("tracking_data", {})

    effective_account = account_id or tracking_data.get("aid", "")

    params = {
        "releasePid": tracking_data.get("pid", ""),
        "account": f"http://access.auth.theplatform.com/data/Account/{effective_account}",
        "schema": "1.0",
        "token": be_token,
    }

    return f"{_LICENSE_BASE_URL}?{urllib.parse.urlencode(params)}"


def _probe_best_mpd(
    http: HttpClient,
    base_mpd_url: str,
) -> str:
    """Try quality variants of an MPD URL and return the best available.

    Mediaset MPD filenames embed a quality tag (``hd``, ``hr``, ``sd``).
    This function tries each variant via HEAD requests and returns the
    first one that responds with HTTP 200.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_mpd_url:
        The original MPD URL from the SMIL manifest.

    Returns
    -------
    str
        The best available MPD URL.  Falls back to the original if
        no variant responds.
    """
    qualities = ["hd", "hr", "sd"]
    parsed = urlparse(base_mpd_url)
    path_parts = parsed.path.rsplit("/", 1)

    if len(path_parts) != 2:
        return base_mpd_url

    dir_path, filename = path_parts

    for target_q in qualities:
        new_filename = filename
        for old_q in qualities:
            if f"{old_q}_" in filename:
                new_filename = filename.replace(f"{old_q}_", f"{target_q}_", 1)
                break

        new_path = f"{dir_path}/{new_filename}"
        candidate = urlunparse(parsed._replace(path=new_path)).strip()

        try:
            # Use a lightweight HEAD request with limited retries.
            resp = http.get(candidate, max_retries=1)
            if resp.status_code == 200:
                log.debug("Best MPD quality found: %s", candidate)
                return candidate
        except Exception:
            continue

    return base_mpd_url


def extract_streams(
    http: HttpClient,
    content_id: str,
    be_token: str,
    account_id: str,
    *,
    is_premium: bool = False,
) -> StreamBundle:
    """Resolve available streams for a Mediaset Infinity content item.

    Parameters
    ----------
    http:
        Shared HTTP client.
    content_id:
        The GUID of the content (film or episode).
    be_token:
        Bearer token for authorization.
    account_id:
        The Mediaset account ID.
    is_premium:
        Whether the user has Infinity+ subscription.

    Returns
    -------
    StreamBundle
        A bundle with the DASH manifest URL, Widevine licence URL,
        and any available subtitles.

    Raises
    ------
    ServiceError
        When no playable stream can be resolved.
    """
    log.info("Extracting streams for content_id=%s", content_id)

    # Step 1: Playback check.
    playback_json = _get_playback_info(http, content_id, be_token)

    # Step 2: SMIL manifest.
    tracking_result = _get_tracking_info(
        http, playback_json, be_token, is_premium=is_premium,
    )

    if not tracking_result or not tracking_result.get("videos"):
        raise ServiceError(
            f"No video streams found for content {content_id}",
            service_name=_SERVICE_TAG,
        )

    # Use the first (best) video entry.
    video_info = tracking_result["videos"][0]
    raw_mpd_url = video_info.get("url", "")

    if not raw_mpd_url:
        raise ServiceError(
            f"Empty MPD URL for content {content_id}",
            service_name=_SERVICE_TAG,
        )

    # Step 3: Probe for best quality MPD.
    mpd_url = _probe_best_mpd(http, raw_mpd_url)

    # Step 4: Generate licence URL.
    license_url = _generate_license_url(video_info, be_token, account_id)

    # Step 5: Build subtitle tracks.
    subtitles: list[SubtitleTrack] = []
    for idx, sub in enumerate(tracking_result.get("subtitles", [])):
        subtitles.append(
            SubtitleTrack(
                id=f"sub_{idx}",
                language=sub.get("language", "und"),
                format=sub.get("format", "vtt"),
            )
        )

    bundle = StreamBundle(
        manifest_url=mpd_url,
        drm_type="widevine",
        license_url=license_url,
        subtitles=subtitles,
    )

    log.info(
        "Resolved DASH stream for %s: %s  (%d subtitle(s))",
        content_id,
        mpd_url,
        len(subtitles),
    )
    return bundle
