"""Stream URL extraction for Crunchyroll.

Resolves DASH (MPD) stream URLs and Widevine DRM licence information
for Crunchyroll content via the ``cr-play-service`` API.

The flow:
    1. Call the play service endpoint to get the MPD URL and playback
       token.
    2. Extract subtitles from the playback response.
    3. Build Widevine licence headers using the playback GUID/token.
    4. Deauthorize the playback session to free the stream slot.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from streamload.core.exceptions import ServiceError
from streamload.models.stream import StreamBundle, SubtitleTrack
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "crunchyroll"
_PLAY_SERVICE_URL = "https://cr-play-service.prd.crunchyrollsvc.com"
_LICENSE_URL = "https://www.crunchyroll.com/license/v1/license/widevine"
_BASE_URL = "https://www.crunchyroll.com"


def _find_token_recursive(obj: object) -> str | None:
    """Recursively search for a ``token`` field in playback response."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() == "token" and isinstance(v, str) and len(v) > 10:
                return v
            found = _find_token_recursive(v)
            if found:
                return found
    elif isinstance(obj, list):
        for el in obj:
            found = _find_token_recursive(el)
            if found:
                return found
    return None


def _extract_subtitles(data: dict) -> list[SubtitleTrack]:
    """Extract all subtitle tracks from playback data.

    Parameters
    ----------
    data:
        The playback response JSON.

    Returns
    -------
    list[SubtitleTrack]
        All available subtitles.
    """
    subtitles: list[SubtitleTrack] = []

    # Regular subtitles.
    subs_obj = data.get("subtitles") or {}
    for lang, info in subs_obj.items():
        if not isinstance(info, dict) or not info.get("url"):
            continue
        subtitles.append(
            SubtitleTrack(
                id=f"sub_{lang}",
                language=lang,
                format=info.get("format") or "ass",
                forced=False,
                name=info.get("display") or info.get("title") or lang,
            )
        )

    # Closed captions.
    captions_obj = data.get("captions") or data.get("closed_captions") or {}
    for lang, info in captions_obj.items():
        if not isinstance(info, dict) or not info.get("url"):
            continue
        subtitles.append(
            SubtitleTrack(
                id=f"cc_{lang}",
                language=lang,
                format=info.get("format") or "vtt",
                forced=False,
                name=info.get("display") or info.get("title") or lang,
            )
        )

    return subtitles


def _build_license_headers(
    base_headers: dict[str, str],
    content_id: str,
    mpd_url: str,
    fallback_token: str | None,
) -> dict[str, str]:
    """Build Widevine licence request headers.

    Parameters
    ----------
    base_headers:
        Base API headers (authorization, user-agent, etc.).
    content_id:
        The media/episode GUID.
    mpd_url:
        The DASH manifest URL (may contain ``playbackGuid`` param).
    fallback_token:
        Fallback token if ``playbackGuid`` is not in the URL.

    Returns
    -------
    dict[str, str]
        Headers for the Widevine licence request.
    """
    query_params = parse_qs(urlparse(mpd_url).query)
    playback_guid = (
        query_params.get("playbackGuid", [fallback_token or ""])[0]
    )

    headers = base_headers.copy()
    headers["x-cr-content-id"] = content_id
    headers["x-cr-video-token"] = playback_guid
    return headers


def _deauth_video(
    http: HttpClient,
    media_id: str,
    token: str,
    access_token: str,
) -> None:
    """Mark a playback session as inactive to free the stream slot.

    Parameters
    ----------
    http:
        Shared HTTP client.
    media_id:
        The content GUID.
    token:
        The playback session token.
    access_token:
        Bearer access token.
    """
    if not media_id or not token:
        return

    url = f"{_PLAY_SERVICE_URL}/v1/token/{media_id}/{token}/inactive"
    headers = {
        "authorization": f"Bearer {access_token}",
        "accept": "application/json, text/plain, */*",
        "origin": _BASE_URL,
        "referer": f"{_BASE_URL}/",
    }

    try:
        http.get(url, headers=headers, max_retries=1)
        log.debug("Deauthorized stream: %s", media_id)
    except Exception:
        log.debug("Failed to deauthorize stream (non-critical): %s", media_id)


def extract_streams(
    http: HttpClient,
    media_id: str,
    access_token: str,
    *,
    locale: str = "it-IT",
) -> StreamBundle:
    """Resolve DASH streams with Widevine DRM for a Crunchyroll episode.

    Parameters
    ----------
    http:
        Shared HTTP client.
    media_id:
        The episode/content GUID.
    access_token:
        Bearer access token.
    locale:
        Locale for the playback request.

    Returns
    -------
    StreamBundle
        A bundle with the DASH manifest URL, Widevine licence URL,
        licence headers, and subtitle tracks.

    Raises
    ------
    ServiceError
        When playback is rejected or unavailable.
    """
    play_url = f"{_PLAY_SERVICE_URL}/v3/{media_id}/web/chrome/play"
    headers = {
        "authorization": f"Bearer {access_token}",
        "accept": "application/json, text/plain, */*",
        "origin": _BASE_URL,
        "referer": f"{_BASE_URL}/",
    }
    params = {"locale": locale}

    log.info("Fetching playback for %s", media_id)
    resp = http.get(play_url, headers=headers, params=params)

    # Handle known error codes.
    if resp.status_code == 403:
        raise ServiceError(
            "Playback rejected: subscription required",
            service_name=_SERVICE_TAG,
        )

    if resp.status_code == 404:
        raise ServiceError(
            f"Playback endpoint not found: {play_url}",
            service_name=_SERVICE_TAG,
        )

    if resp.status_code == 420:
        # Too many active streams.
        try:
            payload = resp.json()
            active_streams = payload.get("activeStreams", [])
            if active_streams:
                log.warning(
                    "Too many active streams (%d), cleaning up",
                    len(active_streams),
                )
                for s in active_streams:
                    if isinstance(s, dict):
                        cid = s.get("contentId")
                        tok = s.get("token")
                        if cid and tok:
                            _deauth_video(http, cid, tok, access_token)
        except Exception:
            pass

        raise ServiceError(
            "Too many active streams -- wait and try again",
            service_name=_SERVICE_TAG,
        )

    resp.raise_for_status()
    data = resp.json()

    if data.get("error") == "Playback is Rejected":
        raise ServiceError(
            "Playback rejected: premium subscription required",
            service_name=_SERVICE_TAG,
        )

    mpd_url = data.get("url", "")
    if not mpd_url:
        raise ServiceError(
            f"No MPD URL in playback response for {media_id}",
            service_name=_SERVICE_TAG,
        )

    token = data.get("token") or _find_token_recursive(data)

    # Build licence headers.
    license_headers = _build_license_headers(
        headers, media_id, mpd_url, token,
    )

    # Extract subtitles.
    subtitles = _extract_subtitles(data)

    # Deauthorize immediately to free stream slot.
    if token:
        _deauth_video(http, media_id, token, access_token)

    bundle = StreamBundle(
        manifest_url=mpd_url,
        drm_type="widevine",
        license_url=_LICENSE_URL,
        subtitles=subtitles,
    )

    log.info(
        "Resolved DASH stream for %s: %s  (%d subtitle(s))",
        media_id,
        mpd_url,
        len(subtitles),
    )
    return bundle
