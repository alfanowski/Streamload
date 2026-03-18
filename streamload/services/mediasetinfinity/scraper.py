"""Web scraping logic for Mediaset Infinity.

Handles search via the GraphQL API and metadata extraction for
seasons/episodes from the Mediaset platform APIs.

Search uses the GraphQL persisted-query interface with SHA256 hashes.
Season and episode data is obtained from the ``theplatform.eu`` feeds
and the Mediaset series API.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "mediasetinfinity"
_BASE_URL = "https://mediasetinfinity.mediaset.it"
_GRAPHQL_URL = "https://mediasetplay.api-graph.mediaset.it/"
_PUBLIC_ID = "PR1GhC"
_FEED_BASE = f"https://feed.entertainment.tv.theplatform.eu/f/{_PUBLIC_ID}"

# Blocks matching these names are skipped when enumerating episode
# categories on season pages.
_BAD_WORDS = [
    "Trailer", "Promo", "Teaser", "Clip", "Backstage", "Le interviste",
    "BALLETTI", "Anteprime web", "I servizi", "Video trend", "Extra",
    "Le trame della settimana", "Esclusive", "INTERVISTE", "SERVIZI",
    "Gossip", "Prossimi appuntamenti tv", "DAYTIME", "Ballo", "Canto",
    "Band", "Senza ADV", "Il serale",
]


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------

@dataclass
class RawTitle:
    """Minimal title record from the GraphQL search response."""

    id: str
    name: str
    type: str  # "tv" | "film"
    url: str
    image_url: str | None = None
    year: str | None = None


@dataclass
class RawSeason:
    """A season from the Mediaset series API."""

    number: int
    title: str
    id: str
    guid: str
    url: str | None = None


@dataclass
class RawEpisode:
    """An episode from the Mediaset feeds."""

    id: str
    name: str
    number: int
    url: str
    duration: int = 0  # minutes
    description: str = ""


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_titles(
    http: HttpClient,
    sha256_hash: str,
    be_token: str,
    client_id: str,
) -> list[RawTitle]:
    """Search Mediaset Infinity via the GraphQL persisted-query API.

    Parameters
    ----------
    http:
        Shared HTTP client.
    sha256_hash:
        The SHA256 hash for the persisted GraphQL search query.
    be_token:
        Bearer token for authorization.
    client_id:
        Device/client UUID.

    Returns
    -------
    list[RawTitle]
        Search results.
    """
    raise NotImplementedError(
        "search_titles requires an initialised MediasetAPI -- "
        "use MediasetInfinityService.search() instead."
    )


def search_titles_with_api(
    http: HttpClient,
    query: str,
    sha256_hash: str,
    request_headers: dict[str, str],
) -> list[RawTitle]:
    """Execute a GraphQL search with pre-built headers.

    Parameters
    ----------
    http:
        Shared HTTP client.
    query:
        Free-text search string.
    sha256_hash:
        The SHA256 hash for the persisted search query.
    request_headers:
        Pre-built headers including authorization.

    Returns
    -------
    list[RawTitle]
        Parsed title records.
    """
    params = {
        "extensions": json.dumps({
            "persistedQuery": {
                "version": 1,
                "sha256Hash": sha256_hash,
            }
        }, separators=(",", ":")),
        "variables": json.dumps({
            "first": 10,
            "property": "search",
            "query": query,
            "uxReference": "filteredSearch",
        }, separators=(",", ":")),
    }

    log.debug("Mediaset search: query=%r  hash=%s", query, sha256_hash[:16])

    try:
        resp = http.get(_GRAPHQL_URL, headers=request_headers, params=params)
        resp.raise_for_status()
    except Exception:
        log.error("Mediaset search request failed", exc_info=True)
        return []

    try:
        resp_json = resp.json()
        items = (
            resp_json.get("data", {})
            .get("getSearchPage", {})
            .get("areaContainersConnection", {})
            .get("areaContainers", [{}])[0]
            .get("areas", [{}])[0]
            .get("sections", [{}])[0]
            .get("collections", [{}])[0]
            .get("itemsConnection", {})
            .get("items", [])
        )
    except (IndexError, KeyError, TypeError):
        log.error("Failed to parse Mediaset search response", exc_info=True)
        return []

    _IMAGE_BASE = "https://img-prod-api2.mediasetplay.mediaset.it/api/images"

    results: list[RawTitle] = []
    for item in items:
        # Determine type.
        is_series = (
            item.get("__typename") == "SeriesItem"
            or item.get("cardLink", {}).get("referenceType") == "series"
            or bool(item.get("seasons"))
        )
        item_type = "tv" if is_series else "film"

        # Extract year.
        date = item.get("year") or ""
        if not date:
            updated = item.get("updated") or item.get("r") or ""
            if updated:
                try:
                    from datetime import datetime
                    date = str(
                        datetime.fromisoformat(
                            str(updated).replace("Z", "+00:00")
                        ).year
                    )
                except Exception:
                    date = ""

        # Build poster image URL.
        image_url: str | None = None
        images = item.get("cardImages", [])
        vertical_image = None
        for img in images:
            if img.get("sourceType") == "image_vertical" or img.get("type") == "image_vertical":
                vertical_image = img
                break

        if vertical_image:
            engine = vertical_image.get("engine", "mse")
            img_id = vertical_image.get("id", "")
            image_url = f"{_IMAGE_BASE}/{engine}/v5/ita/{img_id}/image_vertical/300/450"
            r_val = vertical_image.get("r", "")
            if r_val:
                image_url += f"?r={r_val}"

        results.append(
            RawTitle(
                id=item.get("guid", ""),
                name=item.get("cardTitle", "No Title"),
                type=item_type,
                url=item.get("cardLink", {}).get("value", ""),
                image_url=image_url,
                year=str(date) if date and date != "9999" else None,
            )
        )

    log.info("Mediaset search for %r returned %d title(s)", query, len(results))
    return results


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------

def _extract_serie_id(url: str) -> str | None:
    """Extract the series ID (``SE...``) from a Mediaset URL."""
    try:
        after = url.split("SE", 1)[1]
        after = after.split(",")[0].strip()
        return f"SE{after}"
    except (IndexError, ValueError):
        log.error("Failed to extract serie_id from URL: %s", url)
        return None


def get_series_seasons(
    http: HttpClient,
    series_url: str,
) -> tuple[str, list[RawSeason]]:
    """Fetch seasons for a Mediaset series via the platform API.

    Parameters
    ----------
    http:
        Shared HTTP client.
    series_url:
        The Mediaset page URL for the series.

    Returns
    -------
    tuple[str, list[RawSeason]]
        ``(series_name, seasons)`` sorted by season number ascending.
    """
    serie_id = _extract_serie_id(series_url)
    if not serie_id:
        return "", []

    api_url = f"{_FEED_BASE}/mediaset-prod-all-series-v2"
    params = {"byGuid": serie_id}

    log.debug("Fetching series data: %s  guid=%s", api_url, serie_id)

    try:
        resp = http.get(api_url, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.error("Failed to fetch series data", exc_info=True)
        return "", []

    entries = data.get("entries", [])
    if not entries:
        log.warning("No series entries found for guid=%s", serie_id)
        return "", []

    entry = entries[0]
    series_name = entry.get("title", "")

    tv_seasons = entry.get("seriesTvSeasons", [])
    available_ids = entry.get("availableTvSeasonIds", [])

    seasons: list[RawSeason] = []
    for season_url in available_ids:
        season = next(
            (s for s in tv_seasons if s["id"] == season_url),
            None,
        )
        if not season:
            continue

        seasons.append(
            RawSeason(
                number=season.get("tvSeasonNumber", 0),
                title=season.get("title", ""),
                url=season_url,
                id=str(season_url).rsplit("/", 1)[-1],
                guid=season.get("guid", ""),
            )
        )

    seasons.sort(key=lambda s: s.number)
    log.info("Series %r has %d season(s)", series_name, len(seasons))
    return series_name, seasons


# ---------------------------------------------------------------------------
# Episodes
# ---------------------------------------------------------------------------

def get_season_episodes(
    http: HttpClient,
    season: RawSeason,
) -> list[RawEpisode]:
    """Fetch all episodes for a season from the programs feed.

    Uses the ``mediaset-prod-all-programs-v2`` feed with
    ``byTvSeasonId`` filtering.

    Parameters
    ----------
    http:
        Shared HTTP client.
    season:
        The season to fetch episodes for.

    Returns
    -------
    list[RawEpisode]
        Episodes sorted by episode number.
    """
    programs_url = f"{_FEED_BASE}/mediaset-prod-all-programs-v2"
    params = {
        "byTvSeasonId": season.url or season.id,
        "range": "0-699",
        "sort": ":publishInfo_lastPublished|asc,tvSeasonEpisodeNumber|asc",
    }

    log.debug("Fetching episodes for season %d", season.number)

    try:
        resp = http.get(programs_url, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.error(
            "Failed to fetch episodes for season %d",
            season.number,
            exc_info=True,
        )
        return []

    episodes: list[RawEpisode] = []
    for entry in data.get("entries", []):
        duration_sec = entry.get("mediasetprogram$duration", 0)
        duration_min = int(duration_sec / 60) if duration_sec else 0

        # Skip very short clips (< 10 minutes).
        if duration_min < 10:
            continue

        ep_num = (
            entry.get("tvSeasonEpisodeNumber")
            or entry.get("mediasetprogram$episodeNumber")
        )
        try:
            ep_num = int(ep_num) if ep_num else 0
        except (ValueError, TypeError):
            ep_num = 0

        media_list = entry.get("media", [])
        public_url = ""
        if media_list and isinstance(media_list[0], dict):
            public_url = media_list[0].get("publicUrl", "")

        episodes.append(
            RawEpisode(
                id=entry.get("guid", ""),
                name=entry.get("title", ""),
                number=ep_num,
                url=public_url,
                duration=duration_min,
                description=entry.get("description", ""),
            )
        )

    log.info(
        "Season %d has %d episode(s)",
        season.number,
        len(episodes),
    )
    return episodes


# ---------------------------------------------------------------------------
# SMIL parsing
# ---------------------------------------------------------------------------

def parse_smil_response(smil_xml: str) -> dict:
    """Parse a SMIL response to extract video and subtitle streams.

    Parameters
    ----------
    smil_xml:
        The SMIL XML document as a string.

    Returns
    -------
    dict
        ``{"videos": [...], "subtitles": [...]}`` where each video
        contains ``url``, ``title``, and ``tracking_data``, and each
        subtitle contains ``url``, ``language``, and ``format``.
    """
    root = ET.fromstring(smil_xml)
    ns_match = root.tag.split("}")
    ns = {"smil": ns_match[0].strip("{")} if "}" in root.tag else {}

    videos: list[dict] = []
    subtitles_raw: list[dict] = []

    for par in root.findall(".//smil:par", ns) if ns else root.findall(".//{*}par"):
        # Video from <ref>.
        ref_elem = par.find(".//smil:ref", ns) if ns else par.find(".//{*}ref")
        if ref_elem is not None:
            url = ref_elem.attrib.get("src", "")
            title = ref_elem.attrib.get("title", "")

            tracking_data: dict[str, str] = {}
            params_iter = (
                ref_elem.findall(".//smil:param", ns) if ns
                else ref_elem.findall(".//{*}param")
            )
            for param in params_iter:
                if param.attrib.get("name") == "trackingData":
                    tracking_value = param.attrib.get("value", "")
                    tracking_data = dict(
                        item.split("=", 1)
                        for item in tracking_value.split("|")
                        if "=" in item
                    )
                    break

            if url and url.endswith(".mpd"):
                videos.append({
                    "url": url,
                    "title": title,
                    "tracking_data": tracking_data,
                })

        # Subtitles from <textstream>.
        textstreams = (
            par.findall(".//smil:textstream", ns) if ns
            else par.findall(".//{*}textstream")
        )
        for ts in textstreams:
            sub_url = ts.attrib.get("src", "")
            lang = ts.attrib.get("lang", "unknown")
            sub_type = ts.attrib.get("type", "")
            sub_format = "vtt" if sub_type == "text/vtt" else "srt" if sub_type == "text/srt" else "vtt"

            if sub_url:
                subtitles_raw.append({
                    "url": sub_url,
                    "language": lang,
                    "format": sub_format,
                })

    # Deduplicate subtitles: prefer VTT over SRT per language.
    subs_by_lang: dict[str, list[dict]] = {}
    for sub in subtitles_raw:
        subs_by_lang.setdefault(sub["language"], []).append(sub)

    subtitles: list[dict] = []
    for lang, subs in subs_by_lang.items():
        vtt_subs = [s for s in subs if s["format"] == "vtt"]
        subtitles.append(vtt_subs[0] if vtt_subs else subs[0])

    return {"videos": videos, "subtitles": subtitles}
