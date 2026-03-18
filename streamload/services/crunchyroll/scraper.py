"""Web scraping logic for Crunchyroll.

Handles search via the Crunchyroll discover API and metadata extraction
for seasons/episodes from the CMS v2 API.

All API calls require an authenticated session with a valid access
token, obtained via the ``etp_rt`` cookie grant flow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "crunchyroll"
_BASE_URL = "https://www.crunchyroll.com"
_API_BASE_URL = "https://beta-api.crunchyroll.com"

_EP_NUM_RE = re.compile(r"^\d+(\.\d+)?$")


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------

@dataclass
class RawTitle:
    """Minimal title record from the Crunchyroll search response."""

    id: str
    name: str
    type: str  # "tv" | "film"
    url: str
    image_url: str | None = None
    year: int | None = None


@dataclass
class RawSeason:
    """A season from the Crunchyroll CMS API."""

    id: str
    number: int
    title: str
    slug: str = ""


@dataclass
class RawEpisode:
    """An episode from the Crunchyroll CMS API."""

    id: str
    number: int
    name: str
    url: str
    duration: int = 0  # minutes
    is_special: bool = False
    raw_episode: str = ""
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_titles(
    http: HttpClient,
    query: str,
    access_token: str,
    *,
    locale: str = "it-IT",
) -> list[RawTitle]:
    """Search Crunchyroll via the discover/search REST API.

    Parameters
    ----------
    http:
        Shared HTTP client.
    query:
        Free-text search string.
    access_token:
        Bearer access token.
    locale:
        Locale for results (e.g. ``"it-IT"``).

    Returns
    -------
    list[RawTitle]
        Parsed title records.
    """
    search_url = f"{_BASE_URL}/content/v2/discover/search"
    params = {
        "q": query,
        "n": "20",
        "type": "series,movie_listing",
        "ratings": "true",
        "preferred_audio_language": locale,
        "locale": locale,
    }
    headers = {
        "authorization": f"Bearer {access_token}",
        "accept": "application/json, text/plain, */*",
        "origin": _BASE_URL,
        "referer": f"{_BASE_URL}/",
    }

    log.debug("Crunchyroll search: %s  query=%r", search_url, query)

    try:
        resp = http.get(search_url, headers=headers, params=params)
        resp.raise_for_status()
    except Exception:
        log.error("Crunchyroll search request failed", exc_info=True)
        return []

    data = resp.json()
    seen_ids: set[str] = set()
    results: list[RawTitle] = []

    for block in data.get("data", []):
        block_type = block.get("type")
        if block_type not in ("series", "movie_listing", "top_results"):
            continue

        for item in block.get("items", []):
            item_id = item.get("id")
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            # Determine content type.
            tipo: str | None = None
            if item.get("type") == "movie_listing":
                tipo = "film"
            elif item.get("type") == "series":
                meta = item.get("series_metadata", {})
                # Heuristic: single-episode series might be films.
                if (
                    meta.get("episode_count") == 1
                    and meta.get("season_count", 1) == 1
                    and meta.get("series_launch_year")
                ):
                    description = (item.get("description") or "").lower()
                    if "film" in description or "movie" in description:
                        tipo = "film"
                    else:
                        tipo = "tv"
                else:
                    tipo = "tv"
            else:
                continue

            # Extract poster image.
            poster_image: str | None = None
            images = item.get("images", {})
            poster_wide = images.get("poster_wide")
            if poster_wide and isinstance(poster_wide, list) and poster_wide:
                last_size = poster_wide[0]
                if isinstance(last_size, list) and last_size:
                    poster_image = last_size[-1].get("source")

            url = f"{_BASE_URL}/series/{item_id}"

            results.append(
                RawTitle(
                    id=item_id,
                    name=item.get("title", ""),
                    type=tipo,
                    url=url,
                    image_url=poster_image,
                )
            )

    log.info("Crunchyroll search for %r returned %d title(s)", query, len(results))
    return results


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------

def get_series_seasons(
    http: HttpClient,
    series_id: str,
    access_token: str,
    *,
    locale: str = "it-IT",
) -> tuple[str, list[RawSeason]]:
    """Fetch seasons for a Crunchyroll series via the CMS v2 API.

    Parameters
    ----------
    http:
        Shared HTTP client.
    series_id:
        The Crunchyroll series GUID.
    access_token:
        Bearer access token.
    locale:
        Locale for results.

    Returns
    -------
    tuple[str, list[RawSeason]]
        ``(series_name, seasons)`` sorted by season number.
    """
    headers = {
        "authorization": f"Bearer {access_token}",
        "accept": "application/json, text/plain, */*",
        "origin": _BASE_URL,
        "referer": f"{_BASE_URL}/",
    }
    params = {
        "force_locale": "",
        "preferred_audio_language": locale,
        "locale": locale,
    }

    # Fetch series metadata for title.
    series_name = ""
    meta_url = f"{_API_BASE_URL}/content/v2/cms/series/{series_id}"
    try:
        resp = http.get(meta_url, headers=headers, params=params)
        resp.raise_for_status()
        meta_data = resp.json().get("data", [])
        if meta_data:
            series_name = meta_data[0].get("title", "")
    except Exception:
        log.error("Failed to fetch series title", exc_info=True)

    # Fetch seasons.
    seasons_url = f"{_API_BASE_URL}/content/v2/cms/series/{series_id}/seasons"
    log.debug("Fetching seasons: %s", seasons_url)

    try:
        resp = http.get(seasons_url, headers=headers, params=params)
        resp.raise_for_status()
    except Exception:
        log.error("Failed to fetch seasons", exc_info=True)
        return series_name, []

    data = resp.json()
    raw_seasons_data = data.get("data", [])

    if not series_name and raw_seasons_data:
        series_name = raw_seasons_data[0].get("title", "")

    # Build and sort seasons.
    season_rows: list[dict] = []
    for s in raw_seasons_data:
        raw_num = s.get("season_number", 0)
        season_rows.append({
            "id": s.get("id", ""),
            "title": s.get("title", f"Season {raw_num}"),
            "raw_number": int(raw_num or 0),
            "slug": s.get("slug", ""),
        })

    season_rows.sort(key=lambda r: (r["raw_number"], r["title"] or ""))

    seasons: list[RawSeason] = []
    for idx, row in enumerate(season_rows):
        display_name = row["title"]
        if display_name == series_name:
            display_name = f"Season {row['raw_number']}"

        seasons.append(
            RawSeason(
                id=row["id"],
                number=idx + 1,
                title=display_name,
                slug=row["slug"],
            )
        )

    log.info("Series %r has %d season(s)", series_name, len(seasons))
    return series_name, seasons


# ---------------------------------------------------------------------------
# Episodes
# ---------------------------------------------------------------------------

def _extract_episode_number(ep_data: dict) -> str:
    """Extract the episode number from episode data."""
    meta = ep_data.get("episode_metadata") or {}
    candidates = [
        ep_data.get("episode"),
        meta.get("episode"),
        meta.get("episode_number"),
        ep_data.get("episode_number"),
    ]
    for val in candidates:
        if val is None:
            continue
        val_str = val.strip() if isinstance(val, str) else str(val)
        if val_str:
            return val_str
    return ""


def _is_special(episode_number: str) -> bool:
    """Check if an episode number indicates a special."""
    if not episode_number:
        return True
    return not _EP_NUM_RE.match(episode_number)


def get_season_episodes(
    http: HttpClient,
    season_id: str,
    access_token: str,
    *,
    locale: str = "it-IT",
) -> list[RawEpisode]:
    """Fetch episodes for a Crunchyroll season via the CMS v2 API.

    Parameters
    ----------
    http:
        Shared HTTP client.
    season_id:
        The Crunchyroll season GUID.
    access_token:
        Bearer access token.
    locale:
        Locale for results.

    Returns
    -------
    list[RawEpisode]
        Episodes sorted with normal episodes first, then specials.
    """
    headers = {
        "authorization": f"Bearer {access_token}",
        "accept": "application/json, text/plain, */*",
        "origin": _BASE_URL,
        "referer": f"{_BASE_URL}/",
    }
    params = {
        "force_locale": "",
        "preferred_audio_language": locale,
        "locale": locale,
    }

    episodes_url = f"{_API_BASE_URL}/content/v2/cms/seasons/{season_id}/episodes"
    log.debug("Fetching episodes: %s", episodes_url)

    try:
        resp = http.get(episodes_url, headers=headers, params=params)
        resp.raise_for_status()
    except Exception:
        log.error("Failed to fetch episodes for season %s", season_id, exc_info=True)
        return []

    data = resp.json()
    episodes_data = data.get("data", [])

    raw_episodes: list[dict] = []
    for ep_data in episodes_data:
        ep_number = _extract_episode_number(ep_data)
        special = _is_special(ep_number)
        ep_id = ep_data.get("id", "")
        duration_ms = ep_data.get("duration_ms", 0)

        raw_episodes.append({
            "id": ep_id,
            "number": ep_number,
            "is_special": special,
            "name": ep_data.get("title", f"Episode {ep_data.get('episode_number', '?')}"),
            "url": f"{_BASE_URL}/watch/{ep_id}",
            "duration": int(duration_ms / 60000) if duration_ms else 0,
            "metadata": ep_data,
        })

    # Sort: normal first, then specials.
    normal = [e for e in raw_episodes if not e["is_special"]]
    specials = [e for e in raw_episodes if e["is_special"]]
    ordered = normal + specials

    # Assign display numbers.
    ep_counter = 1
    sp_counter = 1
    episodes: list[RawEpisode] = []
    for ep_dict in ordered:
        if ep_dict["is_special"]:
            display_number = sp_counter
            sp_counter += 1
        else:
            display_number = ep_counter
            ep_counter += 1

        episodes.append(
            RawEpisode(
                id=ep_dict["id"],
                number=display_number,
                name=ep_dict["name"],
                url=ep_dict["url"],
                duration=ep_dict["duration"],
                is_special=ep_dict["is_special"],
                raw_episode=ep_dict["number"],
                metadata=ep_dict.get("metadata", {}),
            )
        )

    log.info("Season %s has %d episode(s)", season_id, len(episodes))
    return episodes
