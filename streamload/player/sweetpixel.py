"""SweetPixel (AnimeWorld) player extractor for Streamload.

Handles extraction of direct MP4 download URLs from the AnimeWorld
download API.  AnimeWorld uses a session-based authentication flow with
CSRF tokens and returns download links via a JSON API endpoint.

The flow:
    1. Fetch the AnimeWorld homepage to obtain session cookies
       (``sessionId``) and the CSRF token from the HTML ``<meta>`` tag.
    2. POST to ``/api/download/{episode_id}`` with session credentials.
    3. Parse the JSON response to extract the server download link.
    4. Strip the redirect wrapper to get the direct MP4 URL.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "sweetpixel"


def get_session_and_csrf(
    http: HttpClient,
    base_url: str,
) -> tuple[str, str]:
    """Fetch AnimeWorld homepage and extract session + CSRF credentials.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        AnimeWorld base URL, e.g. ``"https://www.animeworld.it"``.

    Returns
    -------
    tuple[str, str]
        A 2-tuple of ``(session_id, csrf_token)``.

    Raises
    ------
    ServiceError
        When the session ID or CSRF token cannot be obtained.
    """
    log.debug("Fetching AnimeWorld session from %s", base_url)
    resp = http.get(base_url)
    resp.raise_for_status()

    # Extract session cookie from response headers.
    # The HttpClient wraps cookies in the headers dict; we need to parse
    # the Set-Cookie header.  For simplicity, we re-fetch via the raw
    # response.  The session ID is in the cookies dict.
    session_id: str | None = None

    # Parse cookies from the response header.
    cookie_header = resp.headers.get("set-cookie", "")
    for part in cookie_header.split(","):
        part = part.strip()
        if part.startswith("sessionId="):
            session_id = part.split("=", 1)[1].split(";")[0]
            break

    if not session_id:
        raise ServiceError(
            "Could not obtain AnimeWorld sessionId cookie",
            service_name=_SERVICE_TAG,
        )

    # Extract CSRF token from HTML.
    soup = BeautifulSoup(resp.text, "html.parser")
    csrf_token: str | None = None

    meta_tag = soup.find("meta", {"name": "csrf-token"})
    if meta_tag:
        csrf_token = meta_tag.get("content")

    if not csrf_token:
        input_tag = soup.find("input", {"name": "_csrf"})
        if input_tag:
            csrf_token = input_tag.get("value")

    if not csrf_token:
        raise ServiceError(
            "Could not obtain AnimeWorld CSRF token",
            service_name=_SERVICE_TAG,
        )

    log.debug("Obtained session=%s... csrf=%s...", session_id[:8], csrf_token[:8])
    return session_id, csrf_token


def extract_download_url(
    http: HttpClient,
    base_url: str,
    episode_id: str,
    session_id: str,
    csrf_token: str,
) -> str | None:
    """Resolve the direct MP4 download URL for an AnimeWorld episode.

    Calls the AnimeWorld download API and extracts the server link from
    the JSON response.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        AnimeWorld base URL.
    episode_id:
        The episode ID as used in the download API path.
    session_id:
        Session cookie value obtained from :func:`get_session_and_csrf`.
    csrf_token:
        CSRF token obtained from :func:`get_session_and_csrf`.

    Returns
    -------
    str | None
        The direct MP4 download URL, or ``None`` on failure.
    """
    api_url = f"{base_url}/api/download/{episode_id}"
    log.debug("Calling AnimeWorld download API: %s", api_url)

    headers = {
        "csrf-token": csrf_token,
        "Cookie": f"sessionId={session_id}",
    }

    resp = http.post(api_url, headers=headers)
    if resp.status_code >= 400:
        log.error(
            "AnimeWorld download API returned HTTP %d for episode %s",
            resp.status_code,
            episode_id,
        )
        return None

    try:
        data = resp.json()
    except Exception:
        log.error("Failed to parse AnimeWorld download API JSON")
        return None

    # The response structure is: {"links": {"9": {<server_id>: {"link": "..."}}}}
    # We take the first available server link from provider "9".
    links = data.get("links", {})
    provider = links.get("9", {})
    if not provider:
        # Fall back to any available provider.
        for prov_data in links.values():
            if isinstance(prov_data, dict) and prov_data:
                provider = prov_data
                break

    if not provider:
        log.error("No download links in AnimeWorld response for episode %s", episode_id)
        return None

    # Pick the first server in the provider dict.
    first_server = next(iter(provider.values()), {})
    server_link = first_server.get("link", "")
    if not server_link:
        log.error("Empty server link in AnimeWorld response for episode %s", episode_id)
        return None

    # Strip the redirect wrapper path if present.
    direct_url = server_link.replace("download-file.php?id=", "")
    log.debug("Resolved AnimeWorld MP4 URL: %s", direct_url)
    return direct_url
