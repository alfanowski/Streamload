"""Stream URL extraction for TubiTV.

TubiTV provides HLS streams via its content API.  The playback endpoint
returns manifest URLs and optional DRM (Widevine) licence info.
"""

from __future__ import annotations

import json
import os
import uuid

from streamload.core.exceptions import ServiceError
from streamload.models.stream import StreamBundle
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "tubitv"

_LOGIN_URL = "https://account.production-public.tubi.io/user/login"
_CONTENT_API = "https://content-cdn.production-public.tubi.io/api/v2/content"

# Module-level cache for the bearer token.
_cached_token: str | None = None


def get_bearer_token(
    http: HttpClient,
    email: str | None = None,
    password: str | None = None,
) -> str:
    """Obtain a bearer token for TubiTV API access.

    Authenticates with email/password if provided, otherwise attempts
    anonymous access.  The token is cached for the process lifetime.

    Parameters
    ----------
    http:
        Shared HTTP client.
    email:
        TubiTV account email.
    password:
        TubiTV account password.

    Returns
    -------
    str
        Bearer token string.

    Raises
    ------
    ServiceError
        When authentication fails.
    """
    global _cached_token  # noqa: PLW0603
    if _cached_token:
        return _cached_token

    if not email or not password:
        raise ServiceError(
            "TubiTV requires email and password for API access",
            service_name=_SERVICE_TAG,
        )

    device_id = str(uuid.uuid4())
    login_data = {
        "type": "email",
        "platform": "web",
        "device_id": device_id,
        "credentials": {
            "email": email.strip(),
            "password": password.strip(),
        },
    }

    log.info("Authenticating with TubiTV...")
    try:
        resp = http.post(_LOGIN_URL, json=login_data)
    except Exception as exc:
        raise ServiceError(
            f"TubiTV login request failed: {exc}",
            service_name=_SERVICE_TAG,
        ) from exc

    if resp.status_code == 503:
        raise ServiceError(
            "TubiTV service unavailable (503) -- a US VPN may be required",
            service_name=_SERVICE_TAG,
        )

    resp.raise_for_status()
    data = resp.json()
    _cached_token = data.get("access_token")

    if not _cached_token:
        raise ServiceError(
            "TubiTV login succeeded but no access_token in response",
            service_name=_SERVICE_TAG,
        )

    log.info("TubiTV authentication successful")
    return _cached_token


def get_playback_url(
    http: HttpClient,
    content_id: str,
    bearer_token: str,
) -> tuple[str, str | None]:
    """Get the HLS manifest URL and optional licence URL for playback.

    Parameters
    ----------
    http:
        Shared HTTP client.
    content_id:
        TubiTV content ID (episode or movie).
    bearer_token:
        Bearer token for API authentication.

    Returns
    -------
    tuple[str, str | None]
        ``(manifest_url, license_url)`` where ``license_url`` is
        ``None`` for non-DRM content.

    Raises
    ------
    ServiceError
        When the playback info cannot be retrieved.
    """
    headers = {"authorization": f"Bearer {bearer_token}"}
    params = {
        "content_id": content_id,
        "limit_resolutions[]": ["h264_1080p", "h265_1080p"],
        "video_resources[]": [
            "hlsv6_widevine_nonclearlead",
            "hlsv6_playready_psshv0",
            "hlsv6",
        ],
    }

    log.debug("Fetching TubiTV playback info for content %s", content_id)

    try:
        resp = http.get(_CONTENT_API, headers=headers, params=params)
        resp.raise_for_status()
    except Exception as exc:
        raise ServiceError(
            f"Failed to get TubiTV playback info for {content_id}: {exc}",
            service_name=_SERVICE_TAG,
        ) from exc

    data = resp.json()
    video_resources = data.get("video_resources", [])
    if not video_resources:
        raise ServiceError(
            f"No video resources in TubiTV response for {content_id}",
            service_name=_SERVICE_TAG,
        )

    manifest_url = video_resources[0].get("manifest", {}).get("url", "")
    license_url: str | None = None

    license_server = video_resources[0].get("license_server", {})
    if license_server:
        license_url = license_server.get("url")

    log.debug(
        "TubiTV playback: manifest=%s license=%s",
        manifest_url[:80] if manifest_url else "NONE",
        license_url is not None,
    )
    return manifest_url, license_url


def extract_streams(
    http: HttpClient,
    content_id: str,
    bearer_token: str,
) -> StreamBundle:
    """Resolve HLS streams for a TubiTV content item.

    Parameters
    ----------
    http:
        Shared HTTP client.
    content_id:
        TubiTV content ID.
    bearer_token:
        Bearer token for API authentication.

    Returns
    -------
    StreamBundle
        A bundle with ``manifest_url`` and optional DRM info.

    Raises
    ------
    ServiceError
        When no playable stream can be resolved.
    """
    manifest_url, license_url = get_playback_url(http, content_id, bearer_token)

    if not manifest_url:
        raise ServiceError(
            f"Could not resolve a playable stream for TubiTV content {content_id}",
            service_name=_SERVICE_TAG,
        )

    drm_type: str | None = None
    if license_url:
        drm_type = "widevine"

    log.info("Resolved TubiTV stream for %s: %s", content_id, manifest_url[:80])

    return StreamBundle(
        manifest_url=manifest_url,
        license_url=license_url,
        drm_type=drm_type,
    )
