"""Web scraping logic for TubiTV.

Handles search and metadata extraction from TubiTV.  The site uses a
JSON API for both search and content metadata.

Search: ``https://search.production-public.tubi.io/api/v2/search`` with
``?search={query}`` -- returns a JSON object whose ``contents`` dict maps
content IDs to metadata objects.

Series metadata:
``https://content-cdn.production-public.tubi.io/cms/series/{id}/episodes``
-- returns episodes grouped by season.

Episode playback:
``https://content-cdn.production-public.tubi.io/api/v2/content`` with
``content_id`` and ``video_resources[]`` params -- returns manifest URLs
(HLS) and optional DRM licence info.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "tubitv"

_SEARCH_URL = "https://search.production-public.tubi.io/api/v2/search"
_CONTENT_CDN = "https://content-cdn.production-public.tubi.io"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class _RawTitle:
    """Minimal title record from TubiTV search results."""

    id: str
    title: str
    type: str  # "tv" | "movie"
    year: str | None
    url: str
    image_url: str | None


@dataclass
class _RawEpisode:
    """Minimal episode record from TubiTV series metadata."""

    id: str
    title: str
    number: int
    season_number: int
    duration: int  # seconds


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _title_to_slug(title: str) -> str:
    """Convert a title to a URL-friendly slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug.strip("-")


def _affinity_score(element: dict, keyword: str) -> int:
    """Calculate a rough relevance score for a search result."""
    score = 0
    title = element.get("title", "").lower()
    description = element.get("description", "").lower()
    tags = [t.lower() for t in element.get("tags", [])]
    kw = keyword.lower()

    if kw in title:
        score += 10
    if kw in description:
        score += 5
    if kw in tags:
        score += 3

    return score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_titles(
    http: HttpClient,
    query: str,
    bearer_token: str,
) -> list[_RawTitle]:
    """Search TubiTV for titles matching *query*.

    Parameters
    ----------
    http:
        Shared HTTP client.
    query:
        Free-text search string.
    bearer_token:
        Bearer token for API authentication.

    Returns
    -------
    list[_RawTitle]
        Up to 20 most relevant results, sorted by affinity score.
    """
    headers = {"authorization": f"Bearer {bearer_token}"}
    params = {"search": query}

    log.debug("Searching TubiTV: %s?search=%s", _SEARCH_URL, query)

    try:
        resp = http.get(_SEARCH_URL, headers=headers, params=params)
        resp.raise_for_status()
    except Exception:
        log.error("TubiTV search request failed", exc_info=True)
        return []

    try:
        contents = resp.json().get("contents", {})
        elements = list(contents.values())
    except Exception:
        log.error("Failed to parse TubiTV search JSON", exc_info=True)
        return []

    # Sort by relevance.
    elements.sort(key=lambda x: _affinity_score(x, query), reverse=True)

    results: list[_RawTitle] = []
    for element in elements[:20]:
        try:
            content_type = "tv" if element.get("type", "") == "s" else "movie"
            year = str(element.get("year", "")) or None
            content_id = str(element.get("id", ""))
            title = element.get("title", "")

            # Build URL.
            slug = _title_to_slug(title)
            if content_type == "tv":
                url = f"https://tubitv.com/series/{content_id}/{slug}"
            else:
                url = f"https://tubitv.com/movies/{content_id}/{slug}"

            # Thumbnail.
            thumbnails = element.get("thumbnails", [])
            image_url = thumbnails[0] if thumbnails else None

            results.append(
                _RawTitle(
                    id=content_id,
                    title=title,
                    type=content_type,
                    year=year,
                    url=url,
                    image_url=image_url,
                )
            )

        except Exception:
            log.debug("Error parsing a TubiTV search result", exc_info=True)

    log.info("TubiTV search for %r returned %d result(s)", query, len(results))
    return results


def get_series_seasons(
    http: HttpClient,
    content_id: str,
    bearer_token: str,
) -> dict[int, list[_RawEpisode]]:
    """Fetch all seasons and episodes for a TubiTV series.

    Parameters
    ----------
    http:
        Shared HTTP client.
    content_id:
        TubiTV content ID for the series.
    bearer_token:
        Bearer token for API authentication.

    Returns
    -------
    dict[int, list[_RawEpisode]]
        Mapping of season number to list of episodes.
    """
    headers = {"authorization": f"Bearer {bearer_token}"}
    url = f"{_CONTENT_CDN}/cms/series/{content_id}/episodes"

    log.debug("Fetching TubiTV series metadata: %s", url)

    try:
        resp = http.get(url, headers=headers)
        resp.raise_for_status()
    except Exception:
        log.error("Failed to fetch TubiTV series metadata", exc_info=True)
        return {}

    data = resp.json()
    episodes_by_season = data.get("episodes_by_season", {})

    if not episodes_by_season:
        log.warning("No seasons found in TubiTV response for content %s", content_id)
        return {}

    result: dict[int, list[_RawEpisode]] = {}
    for season_num_str, episodes_list in episodes_by_season.items():
        season_num = int(season_num_str)
        eps: list[_RawEpisode] = []

        for ep in episodes_list:
            eps.append(
                _RawEpisode(
                    id=str(ep.get("id", "")),
                    title=ep.get("title", f"Episode {ep.get('episode_number', '?')}"),
                    number=ep.get("episode_number", 0),
                    season_number=season_num,
                    duration=ep.get("duration", 0),
                )
            )

        eps.sort(key=lambda e: e.number)
        result[season_num] = eps

    log.info(
        "TubiTV series %s has %d season(s), %d total episode(s)",
        content_id, len(result), sum(len(v) for v in result.values()),
    )
    return result


def get_season_episodes_api(
    http: HttpClient,
    content_id: str,
    season_number: int,
    bearer_token: str,
) -> list[_RawEpisode]:
    """Fetch episodes for a specific season via the content API.

    This is a more detailed endpoint that returns full episode metadata
    including playback IDs.

    Parameters
    ----------
    http:
        Shared HTTP client.
    content_id:
        TubiTV content ID for the series.
    season_number:
        1-based season number.
    bearer_token:
        Bearer token for API authentication.

    Returns
    -------
    list[_RawEpisode]
        Episodes for the requested season, sorted by episode number.
    """
    headers = {"authorization": f"Bearer {bearer_token}"}
    params = {
        "app_id": "tubitv",
        "platform": "web",
        "content_id": content_id,
        "pagination[season]": str(season_number),
    }

    url = f"{_CONTENT_CDN}/api/v2/content"
    log.debug("Fetching TubiTV season %d episodes for content %s", season_number, content_id)

    try:
        resp = http.get(url, headers=headers, params=params)
        resp.raise_for_status()
    except Exception:
        log.error("Failed to fetch TubiTV season episodes", exc_info=True)
        return []

    data = resp.json()
    episodes: list[_RawEpisode] = []

    for season_data in data.get("children", []):
        for ep in season_data.get("children", []):
            episodes.append(
                _RawEpisode(
                    id=str(ep.get("id", "")),
                    title=ep.get("title", f"Episode {ep.get('episode_number', '?')}"),
                    number=ep.get("episode_number", 0),
                    season_number=season_number,
                    duration=ep.get("duration", 0),
                )
            )

    episodes.sort(key=lambda e: e.number)
    log.info(
        "TubiTV season %d of content %s has %d episode(s)",
        season_number, content_id, len(episodes),
    )
    return episodes
