"""Web scraping logic for GuardaSerie.

Handles search and metadata extraction from guardaserie.moe.  The site
serves traditional HTML pages with the following structure:

Search: ``/?story={query}&do=search&subaction=search`` -- HTML page with
``div.mlnew`` cards containing title and image info.

Series detail: HTML page with a ``div.tt_season`` containing ``<li>``
elements for each season, and ``div.tab-pane#season-{n}`` containing
episode ``<li>`` elements with ``data-link`` and ``data-num`` attributes.

Player: SuperVideo (packed JS -> jwplayer setup -> HLS).
"""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "guardaserie"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class _RawSerie:
    """Minimal series record parsed from HTML search results."""

    name: str
    url: str
    image_url: str | None


@dataclass
class _RawEpisode:
    """Minimal episode record from the series detail page."""

    number: str
    name: str
    url: str  # primary player URL (data-link)
    fallback_url: str | None = None  # secondary mirror (e.g. Dropload)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_series(
    http: HttpClient,
    base_url: str,
    query: str,
) -> list[_RawSerie]:
    """Search GuardaSerie for series matching *query*.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        Service base URL, e.g. ``"https://guardaserie.moe"``.
    query:
        Free-text search string.

    Returns
    -------
    list[_RawSerie]
        Series results.  Empty list on failure.
    """
    search_url = f"{base_url}/?story={query}&do=search&subaction=search"
    log.debug("Searching GuardaSerie: %s", search_url)

    try:
        resp = http.get(search_url, use_curl=True)
        resp.raise_for_status()
    except Exception:
        log.error("GuardaSerie search request failed", exc_info=True)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[_RawSerie] = []

    for card in soup.find_all("div", class_="mlnew"):
        try:
            link_tag = card.find("a")
            img_tag = card.find("img")
            if not link_tag:
                continue

            raw_name = link_tag.get("title", "")
            # Strip the common "streaming guardaserie" suffix.
            name = raw_name.replace("streaming guardaserie", "").strip()
            url = link_tag.get("href", "")

            image_url: str | None = None
            if img_tag:
                img_src = img_tag.get("src", "")
                if img_src:
                    image_url = (
                        f"{base_url}/{img_src}"
                        if not img_src.startswith("http")
                        else img_src
                    )

            results.append(
                _RawSerie(name=name, url=url, image_url=image_url)
            )

        except Exception:
            log.debug("Error parsing a GuardaSerie search result", exc_info=True)

    log.info("GuardaSerie search for %r returned %d result(s)", query, len(results))
    return results


def get_seasons_count(
    http: HttpClient,
    series_url: str,
) -> tuple[str, int]:
    """Fetch the series detail page and return the title and season count.

    Parameters
    ----------
    http:
        Shared HTTP client.
    series_url:
        Full URL to the series detail page.

    Returns
    -------
    tuple[str, int]
        ``(series_title, season_count)``.
    """
    try:
        resp = http.get(series_url, use_curl=True)
        resp.raise_for_status()
    except Exception:
        log.error("Failed to fetch GuardaSerie series page: %s", series_url, exc_info=True)
        return "Unknown", 0

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract title.
    title_tag = soup.find("h1", class_="front_title")
    title = title_tag.get_text(strip=True) if title_tag else "Unknown"

    # Count seasons.
    season_container = soup.find("div", class_="tt_season")
    if not season_container:
        return title, 0

    season_items = season_container.find_all("li")
    count = len(season_items)

    log.info("Series %r has %d season(s)", title, count)
    return title, count


def get_season_episodes(
    http: HttpClient,
    series_url: str,
    season_number: int,
) -> list[_RawEpisode]:
    """Fetch episodes for a specific season from the series detail page.

    Parameters
    ----------
    http:
        Shared HTTP client.
    series_url:
        Full URL to the series detail page.
    season_number:
        1-based season number.

    Returns
    -------
    list[_RawEpisode]
        Episodes for the requested season.
    """
    try:
        resp = http.get(series_url, use_curl=True)
        resp.raise_for_status()
    except Exception:
        log.error("Failed to fetch GuardaSerie page: %s", series_url, exc_info=True)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find the tab pane for the requested season.
    tab_pane = soup.find("div", class_="tab-pane", id=f"season-{season_number}")
    if not tab_pane:
        log.warning("Season %d tab not found on %s", season_number, series_url)
        return []

    episode_items = tab_pane.find_all("li")
    episodes: list[_RawEpisode] = []

    for ep_li in episode_items:
        # Primary link: the first <a> with data-link attribute.
        ep_link = ep_li.find("a", attrs={"data-link": True}) or ep_li.find("a")
        if not ep_link:
            continue

        data_link = ep_link.get("data-link") or ep_link.get("href") or ""

        # Episode number from data-num attribute.
        data_num = ep_link.get("data-num", "")
        ep_number = data_num.split("x")[-1] if "x" in data_num else data_num

        # Look for a fallback mirror (e.g. Dropload).
        fallback_url: str | None = None
        for anchor in ep_li.find_all("a", attrs={"data-link": True}):
            href = (anchor.get("data-link") or anchor.get("href") or "").lower()
            if "dropload" in href:
                fallback_url = anchor.get("data-link") or anchor.get("href")
                break

        episodes.append(
            _RawEpisode(
                number=ep_number,
                name=f"Episodio {ep_number}",
                url=data_link,
                fallback_url=fallback_url,
            )
        )

    log.info(
        "Season %d of %s has %d episode(s)",
        season_number, series_url, len(episodes),
    )
    return episodes
