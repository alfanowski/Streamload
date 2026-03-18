"""Web scraping logic for RaiPlay.

Handles search via the Atomatic search API and metadata extraction
for seasons/episodes from the RaiPlay program JSON endpoints.

Search uses a JSON POST to the Atomatic ``msearch`` endpoint.
Season/episode data is obtained from the program's JSON descriptor
which contains ``blocks`` with ``sets`` of episodes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "raiplay"
_BASE_URL = "https://www.raiplay.it"
_SEARCH_URL = (
    "https://www.raiplay.it/atomatic/raiplay-search-service/api/v1/msearch"
)

# Template IDs for the Atomatic search API.
_TEMPLATE_IN = "6470a982e4e0301afe1f81f1"
_TEMPLATE_OUT = "6516ac5d40da6c377b151642"

_MAX_SEARCH_RESULTS = 15


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------

@dataclass
class RawTitle:
    """Minimal title record parsed from the Atomatic search response."""

    id: str
    path_id: str
    name: str
    url: str
    image_url: str | None = None
    year: str | None = None


@dataclass
class RawSeason:
    """A season extracted from a RaiPlay program JSON descriptor."""

    number: int
    name: str
    set_id: str
    block_id: str
    episode_count: int = 0


@dataclass
class RawEpisode:
    """An episode extracted from a RaiPlay episodes JSON endpoint."""

    id: str
    number: int
    name: str
    url: str
    video_url: str = ""
    mpd_id: str = ""
    duration: int | None = None  # minutes


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_titles(
    http: HttpClient,
    query: str,
) -> list[RawTitle]:
    """Search RaiPlay for titles matching *query*.

    Uses the Atomatic ``msearch`` JSON POST endpoint.

    Parameters
    ----------
    http:
        Shared HTTP client.
    query:
        Free-text search string.

    Returns
    -------
    list[RawTitle]
        Up to :data:`_MAX_SEARCH_RESULTS` title records.
    """
    json_body = {
        "templateIn": _TEMPLATE_IN,
        "templateOut": _TEMPLATE_OUT,
        "params": {
            "param": query,
            "from": None,
            "sort": "relevance",
            "onlyVideoQuery": False,
        },
    }

    log.debug("RaiPlay search POST: %s  query=%r", _SEARCH_URL, query)

    try:
        resp = http.post(_SEARCH_URL, json=json_body)
        resp.raise_for_status()
    except Exception:
        log.error("RaiPlay search request failed", exc_info=True)
        return []

    try:
        data = resp.json()
        cards = (
            data.get("agg", {})
            .get("titoli", {})
            .get("cards", [])
        )
    except Exception:
        log.error("Failed to parse RaiPlay search response", exc_info=True)
        return []

    results: list[RawTitle] = []
    for item in cards[:_MAX_SEARCH_RESULTS]:
        path_id = item.get("path_id", "")
        if not path_id:
            continue

        # Build absolute image URL.
        image = item.get("immagine", "")
        if image and not image.startswith("http"):
            image = f"{_BASE_URL}{image}"

        # Build absolute page URL.
        url = item.get("url", "")
        if url and not url.startswith("http"):
            url = f"{_BASE_URL}{url}"

        # Best-effort year extraction from the image path.
        year: str | None = None
        if image:
            parts = image.split("/")
            if len(parts) >= 5:
                candidate = parts[-4]
                if candidate.isdigit() and len(candidate) == 4:
                    year = candidate

        results.append(
            RawTitle(
                id=item.get("id", ""),
                path_id=path_id,
                name=item.get("titolo", "Unknown"),
                url=url,
                image_url=image or None,
                year=year,
            )
        )

    log.info("RaiPlay search for %r returned %d title(s)", query, len(results))
    return results


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------

def get_program_seasons(
    http: HttpClient,
    path_id: str,
) -> tuple[str | None, list[RawSeason]]:
    """Fetch program info and extract seasons from content blocks.

    The program JSON contains ``blocks`` of type
    ``"RaiPlay Multimedia Block"`` with ``sets`` representing seasons.
    Blocks named "Clip" or "Extra" are skipped.

    Parameters
    ----------
    http:
        Shared HTTP client.
    path_id:
        The RaiPlay path_id for the program (e.g.
        ``"/programmi/montalbano.json"``).

    Returns
    -------
    tuple[str | None, list[RawSeason]]
        ``(series_name, seasons)``.  The series name is extracted from
        ``program_info.title``.
    """
    path = path_id.lstrip("/")
    program_url = f"{_BASE_URL}/{path}"

    log.debug("Fetching program JSON: %s", program_url)
    resp = http.get(program_url)

    if resp.status_code == 404:
        log.warning("Program not found (404): %s", program_url)
        return None, []

    resp.raise_for_status()
    data = resp.json()

    # Extract basic info.
    program_info = data.get("program_info", {})
    series_name = (
        program_info.get("title")
        or program_info.get("name")
        or ""
    )

    # Skip block types.
    skip_names = {"clip", "extra"}

    seasons: list[RawSeason] = []
    for block in data.get("blocks", []):
        block_type = block.get("type", "")
        block_name = block.get("name", "N/A")
        block_id = block.get("id", "")

        if block_name.lower() in skip_names:
            continue

        if block_type != "RaiPlay Multimedia Block" or "sets" not in block:
            continue

        for season_set in block.get("sets", []):
            episode_size = season_set.get("episode_size", {})
            episode_count = episode_size.get("number", 0)
            if episode_count <= 0:
                continue

            set_name = season_set.get("name", "")
            match = re.search(r"(\d+)", set_name)
            season_number = int(match.group(1)) if match else len(seasons) + 1

            seasons.append(
                RawSeason(
                    number=season_number,
                    name=set_name,
                    set_id=season_set.get("id", ""),
                    block_id=block_id,
                    episode_count=episode_count,
                )
            )

    log.info(
        "Program %r has %d season(s)",
        series_name,
        len(seasons),
    )
    return series_name, seasons


# ---------------------------------------------------------------------------
# Episodes
# ---------------------------------------------------------------------------

def get_season_episodes(
    http: HttpClient,
    path_id: str,
    block_id: str,
    set_id: str,
) -> list[RawEpisode]:
    """Fetch episodes for a specific season.

    Uses the ``episodes.json`` endpoint constructed from the program
    path, block ID, and set ID.

    Parameters
    ----------
    http:
        Shared HTTP client.
    path_id:
        The RaiPlay path_id for the program.
    block_id:
        The block ID containing the season.
    set_id:
        The set ID within the block.

    Returns
    -------
    list[RawEpisode]
        Episode records for this season.
    """
    base_path = path_id.lstrip("/").replace(".json", "")
    url = f"{_BASE_URL}/{base_path}/{block_id}/{set_id}/episodes.json"

    log.debug("Fetching episodes: %s", url)
    resp = http.get(url)
    resp.raise_for_status()
    data = resp.json()

    # Navigate the nested structure: seasons -> episodes -> cards
    cards: list[dict] = []
    for season_data in data.get("seasons", []):
        for episode_group in season_data.get("episodes", []):
            cards.extend(episode_group.get("cards", []))

    # Fallback to direct cards if nested structure not found.
    if not cards:
        cards = data.get("cards", [])

    episodes: list[RawEpisode] = []
    for ep in cards:
        video_url = ep.get("video_url", "")
        mpd_id = ""
        if video_url and "=" in video_url:
            mpd_id = video_url.split("=", 1)[1].strip()

        weblink = ep.get("weblink", "") or ep.get("url", "")
        episode_url = f"{_BASE_URL}{weblink}" if weblink else ""

        ep_number = ep.get("episode")
        if ep_number is not None:
            try:
                ep_number = int(ep_number)
            except (ValueError, TypeError):
                ep_number = 0
        else:
            ep_number = 0

        duration = ep.get("duration") or ep.get("duration_in_minutes")
        if duration is not None:
            try:
                duration = int(duration)
            except (ValueError, TypeError):
                duration = None

        name = (
            ep.get("episode_title")
            or ep.get("name")
            or ep.get("toptitle")
            or f"Episode {ep_number}"
        )

        episodes.append(
            RawEpisode(
                id=ep.get("id", ""),
                number=ep_number,
                name=name,
                url=episode_url,
                video_url=video_url,
                mpd_id=mpd_id,
                duration=duration,
            )
        )

    log.info("Fetched %d episode(s) from %s", len(episodes), url)
    return episodes
