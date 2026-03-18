"""Web scraping logic for AnimeWorld.

Handles search and metadata extraction from www.animeworld.it.  The site
serves traditional HTML pages and does not expose a JSON API for search.

Search: ``/search?keyword={query}`` -- HTML page with ``a.poster`` cards.

Episode listing: HTML parsing of the anime detail page, extracting
``<li class="episode">`` elements with ``data-episode-num`` and
``data-episode-id`` attributes.
"""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "animeworld"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class _RawAnime:
    """Minimal anime record parsed from HTML search results."""

    name: str
    url: str
    type: str  # "TV", "Movie", "ONA"
    is_dubbed: bool
    image_url: str | None


@dataclass
class _RawEpisode:
    """Minimal episode record from the anime detail page."""

    id: str
    number: str
    download_path: str  # e.g. "/api/download/{episode_id}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_anime(
    http: HttpClient,
    base_url: str,
    query: str,
) -> list[_RawAnime]:
    """Search AnimeWorld for anime matching *query*.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        Service base URL, e.g. ``"https://www.animeworld.it"``.
    query:
        Free-text search string.

    Returns
    -------
    list[_RawAnime]
        Anime results.  Empty list on failure.
    """
    search_url = f"{base_url}/search?keyword={query}"
    log.debug("Searching AnimeWorld: %s", search_url)

    try:
        resp = http.get(search_url)
        resp.raise_for_status()
    except Exception:
        log.error("AnimeWorld search request failed", exc_info=True)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[_RawAnime] = []

    for element in soup.find_all("a", class_="poster"):
        try:
            img_tag = element.find("img")
            title = img_tag.get("alt", "") if img_tag else ""
            href = element.get("href", "")
            url = f"{base_url}{href}" if href.startswith("/") else href
            image_url = img_tag.get("src") if img_tag else None

            # Determine type and dub status from status badges.
            status_div = element.find("div", class_="status")
            is_dubbed = False
            anime_type = "TV"

            if status_div:
                if status_div.find("div", class_="dub"):
                    is_dubbed = True
                if status_div.find("div", class_="movie"):
                    anime_type = "Movie"
                elif status_div.find("div", class_="ona"):
                    anime_type = "ONA"

            results.append(
                _RawAnime(
                    name=title,
                    url=url,
                    type=anime_type,
                    is_dubbed=is_dubbed,
                    image_url=image_url,
                )
            )

        except Exception:
            log.debug("Error parsing an AnimeWorld search result", exc_info=True)

    log.info("AnimeWorld search for %r returned %d result(s)", query, len(results))
    return results


def get_anime_title(
    http: HttpClient,
    anime_url: str,
) -> str:
    """Fetch the anime detail page and extract the title.

    Parameters
    ----------
    http:
        Shared HTTP client.
    anime_url:
        Full URL to the anime detail page.

    Returns
    -------
    str
        The anime title, or ``"Unknown"`` on failure.
    """
    try:
        resp = http.get(anime_url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        h1 = soup.find("h1", {"id": "anime-title"})
        if h1:
            return h1.get_text(strip=True)
    except Exception:
        log.debug("Failed to extract anime title from %s", anime_url, exc_info=True)
    return "Unknown"


def get_episodes(
    http: HttpClient,
    anime_url: str,
    session_id: str,
    csrf_token: str,
) -> list[_RawEpisode]:
    """Fetch episodes from the anime detail page.

    Parameters
    ----------
    http:
        Shared HTTP client.
    anime_url:
        Full URL to the anime detail page.
    session_id:
        AnimeWorld session cookie.
    csrf_token:
        CSRF token for API calls.

    Returns
    -------
    list[_RawEpisode]
        Episodes in display order, de-duplicated by ID.
    """
    headers = {
        "csrf-token": csrf_token,
        "Cookie": f"sessionId={session_id}",
    }

    try:
        resp = http.get(anime_url, headers=headers)
        resp.raise_for_status()
    except Exception:
        log.error("Failed to fetch anime page: %s", anime_url, exc_info=True)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    seen_ids: set[str] = set()
    episodes: list[_RawEpisode] = []

    for link in soup.select("li.episode > a"):
        ep_num = link.get("data-episode-num", "0")
        ep_id = link.get("data-episode-id", "")

        if not ep_id or ep_id in seen_ids:
            continue
        seen_ids.add(ep_id)

        episodes.append(
            _RawEpisode(
                id=ep_id,
                number=ep_num,
                download_path=f"/api/download/{ep_id}",
            )
        )

    log.info("Fetched %d episode(s) from %s", len(episodes), anime_url)
    return episodes
