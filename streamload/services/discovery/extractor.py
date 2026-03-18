"""Stream URL extraction for Discovery+.

Discovery+ provides DASH/HLS streams with Widevine or PlayReady DRM.
Playback info is obtained from a playback orchestration endpoint that
returns manifest URLs and DRM licence server details.
"""

from __future__ import annotations

import uuid

from streamload.core.exceptions import ServiceError
from streamload.models.stream import StreamBundle
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

from .scraper import DiscoveryClient

log = get_logger(__name__)

_SERVICE_TAG = "discovery"


def extract_streams(
    http: HttpClient,
    client: DiscoveryClient,
    edit_id: str,
) -> StreamBundle:
    """Resolve streams for a Discovery+ content item.

    Supports both anonymous and authenticated playback modes.

    Parameters
    ----------
    http:
        Shared HTTP client.
    client:
        Authenticated Discovery+ client.
    edit_id:
        The edit ID (or video ID for anonymous mode) of the content.

    Returns
    -------
    StreamBundle
        A bundle with ``manifest_url`` and DRM info.

    Raises
    ------
    ServiceError
        When no playable stream can be resolved.
    """
    log.info("Extracting Discovery+ streams for %s (anonymous=%s)", edit_id, client.is_anonymous)

    if client.is_anonymous:
        return _extract_anonymous(http, client, edit_id)
    else:
        return _extract_authenticated(http, client, edit_id)


def _extract_anonymous(
    http: HttpClient,
    client: DiscoveryClient,
    video_id: str,
) -> StreamBundle:
    """Get playback info using anonymous bearer token."""
    cookies = {"st": client.bearer_token} if client.bearer_token else {}

    headers = {
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ),
        "x-disco-client": "WEB:UNKNOWN:dsc:4.4.1",
    }

    json_data = {
        "videoId": video_id,
        "wisteriaProperties": {
            "advertiser": {},
            "appBundle": "",
            "device": {
                "browser": {"name": "chrome", "version": "125.0.0.0"},
                "id": "",
                "language": "en-US",
                "make": "",
                "model": "",
                "name": "chrome",
                "os": "Windows",
                "osVersion": "NT 10.0",
                "player": {
                    "name": "Discovery Player Web",
                    "version": "3.1.0",
                },
                "type": "desktop",
            },
            "gdpr": 0,
            "platform": "desktop",
            "product": "dsc",
            "siteId": "dsc",
        },
        "deviceInfo": {
            "adBlocker": False,
            "deviceId": "",
            "drmTypes": {
                "widevine": False,
                "playready": True,
                "fairplay": True,
                "clearkey": True,
            },
            "drmSupported": True,
        },
    }

    try:
        resp = http.post(
            "https://eu1-prod-direct.discoveryplus.com/playback/v3/videoPlaybackInfo",
            headers=headers,
            json=json_data,
            use_curl=True,
        )
    except Exception as exc:
        raise ServiceError(
            f"Discovery+ playback request failed: {exc}",
            service_name=_SERVICE_TAG,
        ) from exc

    if resp.status_code == 403:
        data = resp.json()
        errors = data.get("errors", [])
        if errors and errors[0].get("code") == "access.denied.missingpackage":
            raise ServiceError(
                "Content requires a Discovery+ subscription",
                service_name=_SERVICE_TAG,
            )
        raise ServiceError(
            "Content is geo-restricted on Discovery+",
            service_name=_SERVICE_TAG,
        )

    resp.raise_for_status()
    data = resp.json()

    streaming = data["data"]["attributes"]["streaming"]
    if not streaming:
        raise ServiceError(
            f"No streaming data in Discovery+ response for {video_id}",
            service_name=_SERVICE_TAG,
        )

    manifest_url = streaming[0].get("url", "")
    stream_type = streaming[0].get("type", "hls")

    # Extract DRM info.
    protection = streaming[0].get("protection", {})
    schemes = protection.get("schemes", {})
    license_url: str | None = None
    drm_type: str | None = None

    widevine = schemes.get("widevine")
    playready = schemes.get("playready")

    if widevine:
        license_url = widevine.get("licenseUrl")
        drm_type = "widevine"
    elif playready:
        license_url = playready.get("licenseUrl")
        drm_type = "playready"

    log.info(
        "Resolved Discovery+ stream: type=%s drm=%s manifest=%s",
        stream_type, drm_type, manifest_url[:80] if manifest_url else "NONE",
    )

    return StreamBundle(
        manifest_url=manifest_url,
        license_url=license_url,
        drm_type=drm_type,
    )


def _extract_authenticated(
    http: HttpClient,
    client: DiscoveryClient,
    edit_id: str,
) -> StreamBundle:
    """Get playback info using authenticated access token."""
    url = (
        f"{client.base_url}/playback-orchestrator/any/"
        f"playback-orchestrator/v1/playbackInfo"
    )

    headers = client.headers.copy()
    headers["Authorization"] = f"Bearer {client.access_token}"

    payload = {
        "appBundle": "com.wbd.stream",
        "applicationSessionId": client.device_id,
        "capabilities": {
            "codecs": {
                "audio": {
                    "decoders": [
                        {"codec": "aac", "profiles": ["lc", "he", "hev2", "xhe"]},
                        {"codec": "eac3", "profiles": ["atmos"]},
                    ]
                },
                "video": {
                    "decoders": [
                        {
                            "codec": "h264",
                            "levelConstraints": {
                                "framerate": {"max": 60, "min": 0},
                                "height": {"max": 2160, "min": 48},
                                "width": {"max": 3840, "min": 48},
                            },
                            "maxLevel": "5.2",
                            "profiles": ["baseline", "main", "high"],
                        },
                        {
                            "codec": "h265",
                            "levelConstraints": {
                                "framerate": {"max": 60, "min": 0},
                                "height": {"max": 2160, "min": 144},
                                "width": {"max": 3840, "min": 144},
                            },
                            "maxLevel": "5.1",
                            "profiles": ["main10", "main"],
                        },
                    ],
                    "hdrFormats": [
                        "hdr10", "hdr10plus", "dolbyvision",
                        "dolbyvision5", "dolbyvision8", "hlg",
                    ],
                },
            },
            "contentProtection": {
                "contentDecryptionModules": [
                    {"drmKeySystem": "playready", "maxSecurityLevel": "SL3000"}
                ]
            },
            "manifests": {"formats": {"dash": {}}},
        },
        "consumptionType": "streaming",
        "deviceInfo": {
            "player": {
                "mediaEngine": {"name": "", "version": ""},
                "playerView": {"height": 2160, "width": 3840},
                "sdk": {"name": "", "version": ""},
            }
        },
        "editId": edit_id,
        "firstPlay": False,
        "gdpr": False,
        "playbackSessionId": str(uuid.uuid4()),
        "userPreferences": {},
    }

    try:
        resp = http.post(url, headers=headers, json=payload, use_curl=True)
        resp.raise_for_status()
    except Exception as exc:
        raise ServiceError(
            f"Discovery+ authenticated playback request failed: {exc}",
            service_name=_SERVICE_TAG,
        ) from exc

    data = resp.json()

    # Extract manifest URL (prefer fallback without _fallback suffix).
    manifest_url = (
        data.get("fallback", {}).get("manifest", {}).get("url", "").replace("_fallback", "")
        or data.get("manifest", {}).get("url", "")
    )

    # Extract licence URL.
    license_url = (
        data.get("fallback", {}).get("drm", {}).get("schemes", {}).get("playready", {}).get("licenseUrl")
        or data.get("drm", {}).get("schemes", {}).get("playready", {}).get("licenseUrl")
    )

    drm_type: str | None = "playready" if license_url else None

    log.info(
        "Resolved Discovery+ authenticated stream: drm=%s manifest=%s",
        drm_type, manifest_url[:80] if manifest_url else "NONE",
    )

    return StreamBundle(
        manifest_url=manifest_url,
        license_url=license_url,
        drm_type=drm_type,
    )
