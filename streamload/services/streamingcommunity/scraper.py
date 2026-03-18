"""Web scraping logic for StreamingCommunity.

Handles search and metadata extraction using the Inertia.js-based API
that powers the StreamingCommunity frontend.  The site serves a
server-rendered initial page whose ``<div id="app" data-page="...">``
attribute contains JSON with the Inertia protocol version, then
subsequent requests with ``x-inertia`` / ``x-inertia-version`` headers
return pure JSON responses.

Search is performed across both ``/it`` and ``/en`` language paths to
maximize coverage.  Results are de-duplicated by title ID.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from bs4 import BeautifulSoup

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "streamingcommunity"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

@dataclass
class _RawTitle:
    """Minimal title record parsed directly from the API response."""

    id: int
    slug: str
    name: str
    type: str  # "movie" | "tv"
    year: str | None
    image_url: str | None
    language: str  # "it" | "en" -- the path used to find this title


def _get_inertia_version(http: HttpClient, base_url: str, lang: str) -> str | None:
    """Fetch the site root and extract the Inertia protocol version.

    The version string is embedded inside the ``data-page`` JSON
    attribute of ``<div id="app">``.

    Returns ``None`` when the version cannot be determined (the page
    structure may have changed).
    """
    url = f"{base_url}/{lang}"
    log.debug("Fetching Inertia version from %s", url)

    resp = http.get(url, use_curl=True)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    app_div = soup.find("div", {"id": "app"})
    if app_div is None or not app_div.get("data-page"):
        log.warning("No <div id='app' data-page='...'> found at %s", url)
        return None

    try:
        page_data = json.loads(app_div["data-page"])
        version = page_data.get("version")
        log.debug("Inertia version for lang=%s: %s", lang, version)
        return version
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        log.warning("Failed to parse Inertia page data at %s: %s", url, exc)
        return None


def _extract_year(title_data: dict) -> str | None:
    """Best-effort year extraction from a single title dict.

    Priority:
        1. ``translations`` where ``key == "first_air_date"``
        2. ``translations`` where ``key == "release_date"``
        3. Root-level ``last_air_date`` or ``release_date``
    """
    for key in ("first_air_date", "release_date"):
        for trans in title_data.get("translations") or []:
            if trans.get("key") == key and trans.get("value"):
                raw = trans["value"]
                return raw.split("-")[0] if "-" in raw else raw

    for field in ("last_air_date", "release_date"):
        raw = title_data.get(field)
        if raw:
            return raw.split("-")[0] if "-" in raw else raw

    return None


def _extract_image_url(title_data: dict, base_url: str) -> str | None:
    """Build a CDN image URL from the title's ``images`` list.

    Prefers ``poster`` > ``cover`` > ``cover_mobile`` > ``background``
    image types, falling back to the first available image.
    """
    images = title_data.get("images") or []
    if not images:
        return None

    preferred = ("poster", "cover", "cover_mobile", "background")
    filename: str | None = None

    for ptype in preferred:
        for img in images:
            if img.get("type") == ptype and img.get("filename"):
                filename = img["filename"]
                break
        if filename:
            break

    if not filename:
        filename = images[0].get("filename")

    if not filename:
        return None

    # CDN domain follows the pattern: cdn.{domain} (e.g. cdn.streamingcommunity.prof)
    cdn_url = base_url.replace("https://", "https://cdn.", 1)
    return f"{cdn_url}/images/{filename}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_titles(
    http: HttpClient,
    base_url: str,
    query: str,
) -> list[_RawTitle]:
    """Search StreamingCommunity for titles matching *query*.

    Queries both the ``/it`` and ``/en`` language paths and returns
    de-duplicated results ordered by their API position (most relevant
    first).

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        Service base URL without trailing slash, e.g.
        ``"https://streamingcommunity.prof"``.
    query:
        Free-text search string.

    Returns
    -------
    list[_RawTitle]
        De-duplicated title records.  Empty list on total failure.
    """
    results: list[_RawTitle] = []
    seen_ids: set[int] = set()

    for lang in ("it", "en"):
        version = _get_inertia_version(http, base_url, lang)
        if version is None:
            log.warning("Skipping lang=%s -- could not obtain Inertia version", lang)
            continue

        search_url = f"{base_url}/{lang}/search"
        inertia_headers = {
            "x-inertia": "true",
            "x-inertia-version": version,
        }

        log.debug("Searching %s?q=%s", search_url, query)
        try:
            resp = http.get(search_url, headers=inertia_headers, params={"q": query}, use_curl=True)
            resp.raise_for_status()
        except Exception:
            log.error("Search request failed for lang=%s", lang, exc_info=True)
            continue

        try:
            titles_data = resp.json().get("props", {}).get("titles") or []
        except Exception:
            log.error("Failed to parse search JSON for lang=%s", lang, exc_info=True)
            continue

        for item in titles_data:
            title_id = item.get("id")
            if title_id is None or title_id in seen_ids:
                continue
            seen_ids.add(title_id)

            results.append(
                _RawTitle(
                    id=title_id,
                    slug=item.get("slug", ""),
                    name=item.get("name", ""),
                    type=item.get("type", ""),
                    year=_extract_year(item),
                    image_url=_extract_image_url(item, base_url),
                    language=lang,
                )
            )

    log.info("Search for %r returned %d title(s)", query, len(results))
    return results


def get_title_seasons(
    http: HttpClient,
    base_url: str,
    media_id: int,
    slug: str,
    lang: str = "it",
) -> tuple[str, list[dict]]:
    """Fetch the title detail page and return season metadata.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        Service base URL.
    media_id:
        Numeric title ID.
    slug:
        URL slug for the title (used to build the canonical path).
    lang:
        Language code (``"it"`` or ``"en"``).

    Returns
    -------
    tuple[str, list[dict]]
        A 2-tuple of ``(inertia_version, seasons_list)`` where each
        season dict contains at least ``id``, ``number``, and optionally
        ``slug``.
    """
    url = f"{base_url}/{lang}/titles/{media_id}-{slug}"
    log.debug("Fetching title page: %s", url)

    resp = http.get(url, use_curl=True)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    app_div = soup.find("div", {"id": "app"})
    if app_div is None or not app_div.get("data-page"):
        raise ServiceError(
            f"No Inertia data-page on {url}",
            service_name=_SERVICE_TAG,
        )

    page_data = json.loads(app_div["data-page"])
    version = page_data.get("version", "")
    title_props = page_data.get("props", {}).get("title", {})
    seasons_data: list[dict] = title_props.get("seasons") or []

    log.info(
        "Title %d (%s) has %d season(s)",
        media_id,
        slug,
        len(seasons_data),
    )
    return version, seasons_data


def get_season_episodes(
    http: HttpClient,
    base_url: str,
    media_id: int,
    slug: str,
    season_number: int,
    inertia_version: str,
    lang: str = "it",
) -> list[dict]:
    """Fetch episode data for a specific season via the Inertia API.

    Parameters
    ----------
    http:
        Shared HTTP client.
    base_url:
        Service base URL.
    media_id:
        Numeric title ID.
    slug:
        Title URL slug.
    season_number:
        1-based season number.
    inertia_version:
        The Inertia version obtained from the title page.
    lang:
        Language code.

    Returns
    -------
    list[dict]
        Episode dicts, each containing at least ``id``, ``number``,
        ``name``, and ``duration``.
    """
    url = f"{base_url}/{lang}/titles/{media_id}-{slug}/season-{season_number}"
    inertia_headers = {
        "x-inertia": "true",
        "x-inertia-version": inertia_version,
    }

    log.debug("Fetching season %d episodes: %s", season_number, url)
    resp = http.get(url, headers=inertia_headers, use_curl=True)
    resp.raise_for_status()

    episodes: list[dict] = (
        resp.json()
        .get("props", {})
        .get("loadedSeason", {})
        .get("episodes") or []
    )
    log.info(
        "Season %d of title %d has %d episode(s)",
        season_number,
        media_id,
        len(episodes),
    )
    return episodes
