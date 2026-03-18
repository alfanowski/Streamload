"""Web scraping logic for AnimeUnity.

Handles search and metadata extraction from animeunity.so.  The site
uses CSRF-protected POST endpoints for searching:

- ``/livesearch`` -- fast title search (returns partial matches).
- ``/archivio/get-animes`` -- archive search with filters (returns
  paginated results with richer metadata).

Episode data is fetched from the ``/info_api/{media_id}/`` REST endpoint,
with pagination support for long-running series (120 episodes per chunk).
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "animeunity"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class _RawAnime:
    """Minimal anime record parsed directly from the API response."""

    id: int
    slug: str
    name: str
    type: str  # "TV", "Movie", "OVA", "ONA", ...
    episodes_count: int
    image_url: str | None
    status: str | None = None


@dataclass
class _RawEpisode:
    """Minimal episode record from the info API."""

    id: int
    number: str  # may be fractional, e.g. "6.5"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_session_tokens(http: HttpClient, base_url: str) -> dict[str, str]:
    """Fetch the site root to obtain XSRF-TOKEN and session cookies.

    Returns a dict with keys ``XSRF-TOKEN`` and ``animeunity_session``,
    both URL-decoded.

    Raises
    ------
    ServiceError
        When the cookies cannot be obtained (site down / blocked).
    """
    log.debug("Fetching AnimeUnity session tokens from %s", base_url)
    resp = http.get(base_url, use_curl=True)
    resp.raise_for_status()

    # Parse Set-Cookie headers.
    raw_cookies: dict[str, str] = {}
    cookie_header = resp.headers.get("set-cookie", "")
    for segment in cookie_header.replace(", ", "\n").split("\n"):
        segment = segment.strip()
        if "=" in segment:
            key, _, val = segment.partition("=")
            val = val.split(";")[0]
            raw_cookies[key.strip()] = urllib.parse.unquote(val.strip())

    tokens = {
        "XSRF-TOKEN": raw_cookies.get("XSRF-TOKEN", ""),
        "animeunity_session": raw_cookies.get("animeunity_session", ""),
    }
    log.debug("Session tokens obtained: XSRF=%s...", tokens["XSRF-TOKEN"][:20] if tokens["XSRF-TOKEN"] else "EMPTY")
    return tokens


def _get_real_title(record: dict) -> str:
    """Return the most appropriate title from an anime record dict.

    Priority: ``title_eng`` > ``title`` > ``title_it`` > ``""``.
    """
    return (
        record.get("title_eng")
        or record.get("title")
        or record.get("title_it")
        or ""
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_anime(
    http: HttpClient,
    base_url: str,
    query: str,
) -> list[_RawAnime]:
    """Search AnimeUnity for anime matching *query*.

    Queries both the ``/livesearch`` and ``/archivio/get-animes``
    endpoints and returns de-duplicated results.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        Service base URL, e.g. ``"https://animeunity.so"``.
    query:
        Free-text search string.

    Returns
    -------
    list[_RawAnime]
        De-duplicated anime records.  Empty list on total failure.
    """
    tokens = _get_session_tokens(http, base_url)

    cookies_header = (
        f"XSRF-TOKEN={urllib.parse.quote(tokens['XSRF-TOKEN'])}; "
        f"animeunity_session={urllib.parse.quote(tokens['animeunity_session'])}"
    )
    headers = {
        "origin": base_url,
        "referer": f"{base_url}/",
        "x-xsrf-token": tokens["XSRF-TOKEN"],
        "Cookie": cookies_header,
    }

    results: list[_RawAnime] = []
    seen_ids: set[int] = set()

    # -- Pass 1: livesearch ------------------------------------------------
    try:
        resp = http.post(
            f"{base_url}/livesearch",
            headers=headers,
            data={"title": query},
            use_curl=True,
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])
        _process_records(records, seen_ids, results)
        log.debug("livesearch returned %d record(s)", len(records))
    except Exception:
        log.error("AnimeUnity livesearch failed", exc_info=True)

    # -- Pass 2: archivio -------------------------------------------------
    try:
        json_data = {
            "title": query,
            "type": False,
            "year": False,
            "order": False,
            "status": False,
            "genres": False,
            "offset": 0,
            "dubbed": False,
            "season": False,
        }
        resp = http.post(
            f"{base_url}/archivio/get-animes",
            headers=headers,
            json=json_data,
            use_curl=True,
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])
        _process_records(records, seen_ids, results)
        log.debug("archivio returned %d record(s)", len(records))
    except Exception:
        log.error("AnimeUnity archivio search failed", exc_info=True)

    log.info("Search for %r returned %d anime(s)", query, len(results))
    return results


def _process_records(
    records: list[dict],
    seen_ids: set[int],
    results: list[_RawAnime],
) -> None:
    """Process raw API records, de-duplicate, and append to *results*."""
    for record in records:
        title_id = record.get("id")
        if title_id is None or title_id in seen_ids:
            continue
        seen_ids.add(title_id)

        results.append(
            _RawAnime(
                id=title_id,
                slug=record.get("slug", ""),
                name=_get_real_title(record),
                type=record.get("type", "TV"),
                episodes_count=record.get("episodes_count", 0),
                image_url=record.get("imageurl"),
                status=record.get("status"),
            )
        )


def get_episode_count(
    http: HttpClient,
    base_url: str,
    media_id: int,
) -> int:
    """Fetch the total episode count for an anime.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        Service base URL.
    media_id:
        AnimeUnity internal anime ID.

    Returns
    -------
    int
        Total episode count, or 0 on failure.
    """
    try:
        resp = http.get(f"{base_url}/info_api/{media_id}/")
        resp.raise_for_status()
        return resp.json().get("episodes_count", 0)
    except Exception:
        log.error("Failed to fetch episode count for anime %d", media_id, exc_info=True)
        return 0


def get_episodes(
    http: HttpClient,
    base_url: str,
    media_id: int,
) -> list[_RawEpisode]:
    """Fetch all episodes for an anime, paginating in chunks of 120.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        Service base URL.
    media_id:
        AnimeUnity internal anime ID.

    Returns
    -------
    list[_RawEpisode]
        All episodes ordered by number.
    """
    total = get_episode_count(http, base_url, media_id)
    if total <= 0:
        return []

    all_episodes: list[_RawEpisode] = []
    start = 1

    while start <= total:
        end = min(start + 119, total)
        params = {"start_range": str(start), "end_range": str(end)}
        try:
            resp = http.get(
                f"{base_url}/info_api/{media_id}/1",
                params=params,
            )
            resp.raise_for_status()
            chunk = resp.json().get("episodes", [])
            for ep in chunk:
                all_episodes.append(
                    _RawEpisode(
                        id=ep.get("id", 0),
                        number=str(ep.get("number", 0)),
                    )
                )
        except Exception:
            log.error(
                "Failed to fetch episodes %d-%d for anime %d",
                start, end, media_id,
                exc_info=True,
            )

        start = end + 1

    log.info("Fetched %d episode(s) for anime %d", len(all_episodes), media_id)
    return all_episodes
