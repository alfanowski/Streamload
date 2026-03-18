"""TMDB API client for metadata enrichment.

Queries The Movie Database (v3) to enrich search results with release
year, genre, description, and poster URLs.  Designed to be non-disruptive:
every public method swallows exceptions and returns gracefully so a TMDB
outage never blocks the download workflow.

Usage::

    from streamload.utils.tmdb import TMDBClient
    from streamload.utils.http import HttpClient

    with HttpClient() as http:
        tmdb = TMDBClient(api_key="...", http_client=http)
        entry = tmdb.enrich_entry(entry)
"""

from __future__ import annotations

from typing import Any

from streamload.models.media import MediaEntry, MediaType
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)


class TMDBClient:
    """Client for The Movie Database API (v3).

    Used to enrich search results with:
    - Year of release
    - Genre
    - Description/overview
    - Poster image URL
    """

    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

    # Genre ID to name mapping (TMDB genre IDs are stable).
    MOVIE_GENRES: dict[int, str] = {
        28: "Action",
        12: "Adventure",
        16: "Animation",
        35: "Comedy",
        80: "Crime",
        99: "Documentary",
        18: "Drama",
        10751: "Family",
        14: "Fantasy",
        36: "History",
        27: "Horror",
        10402: "Music",
        9648: "Mystery",
        10749: "Romance",
        878: "Sci-Fi",
        10770: "TV Movie",
        53: "Thriller",
        10752: "War",
        37: "Western",
    }
    TV_GENRES: dict[int, str] = {
        10759: "Action & Adventure",
        16: "Animation",
        35: "Comedy",
        80: "Crime",
        99: "Documentary",
        18: "Drama",
        10751: "Family",
        10762: "Kids",
        9648: "Mystery",
        10763: "News",
        10764: "Reality",
        10765: "Sci-Fi & Fantasy",
        10766: "Soap",
        10767: "Talk",
        10768: "War & Politics",
        37: "Western",
    }

    def __init__(self, api_key: str, http_client: HttpClient) -> None:
        self._api_key = api_key
        self._http = http_client
        self._enabled = bool(api_key)

    @property
    def enabled(self) -> bool:
        """Whether a TMDB API key was provided and lookups are active."""
        return self._enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_movie(
        self,
        title: str,
        year: int | None = None,
        language: str = "it-IT",
    ) -> dict[str, Any] | None:
        """Search for a movie on TMDB.  Returns first match or ``None``.

        GET /search/movie?query={title}&year={year}&language={language}
        """
        if not self._enabled:
            return None

        params: dict[str, str] = {"query": title, "language": language}
        if year is not None:
            params["year"] = str(year)

        data = self._get("/search/movie", params=params)
        if data is None:
            return None

        results: list[dict[str, Any]] = data.get("results") or []
        if not results:
            log.debug("TMDB movie search for %r returned no results", title)
            return None

        return results[0]

    def search_tv(
        self,
        title: str,
        year: int | None = None,
        language: str = "it-IT",
    ) -> dict[str, Any] | None:
        """Search for a TV show on TMDB.  Returns first match or ``None``.

        GET /search/tv?query={title}&year={year}&language={language}
        """
        if not self._enabled:
            return None

        params: dict[str, str] = {"query": title, "language": language}
        if year is not None:
            params["first_air_date_year"] = str(year)

        data = self._get("/search/tv", params=params)
        if data is None:
            return None

        results: list[dict[str, Any]] = data.get("results") or []
        if not results:
            log.debug("TMDB TV search for %r returned no results", title)
            return None

        return results[0]

    def enrich_entry(
        self,
        entry: MediaEntry,
        language: str = "it-IT",
    ) -> MediaEntry:
        """Enrich a :class:`MediaEntry` with TMDB metadata.

        Searches TMDB based on ``entry.type``, fills in:
        - ``year``  (from ``release_date`` or ``first_air_date``)
        - ``genre`` (from ``genre_ids`` mapped to names)
        - ``description`` (from ``overview``)
        - ``image_url`` (from ``poster_path``)

        Returns the entry (modified in place) even if TMDB lookup fails.
        Never raises -- failures are logged and entry returned as-is.
        """
        if not self._enabled:
            return entry

        try:
            return self._do_enrich(entry, language)
        except Exception:  # noqa: BLE001
            log.warning(
                "TMDB enrichment failed for %r (type=%s)",
                entry.title,
                entry.type.value,
                exc_info=True,
            )
            return entry

    def enrich_entries(
        self,
        entries: list[MediaEntry],
        language: str = "it-IT",
    ) -> list[MediaEntry]:
        """Enrich multiple entries.  Skips entries that already have ``year`` set."""
        if not self._enabled:
            return entries

        for entry in entries:
            if entry.year is not None:
                continue
            self.enrich_entry(entry, language=language)

        return entries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_enrich(self, entry: MediaEntry, language: str) -> MediaEntry:
        """Core enrichment logic, called inside the exception guard."""
        is_movie = entry.type == MediaType.FILM

        if is_movie:
            result = self.search_movie(entry.title, year=entry.year, language=language)
        else:
            # SERIE and ANIME both map to TMDB's TV search.
            result = self.search_tv(entry.title, year=entry.year, language=language)

        if result is None:
            return entry

        # -- Year ----------------------------------------------------------
        date_key = "release_date" if is_movie else "first_air_date"
        raw_date: str = result.get(date_key) or ""
        if raw_date and len(raw_date) >= 4:
            try:
                entry.year = int(raw_date[:4])
            except ValueError:
                pass

        # -- Genre ---------------------------------------------------------
        genre_ids: list[int] = result.get("genre_ids") or []
        genre_map = self.MOVIE_GENRES if is_movie else self.TV_GENRES
        genre_names = [genre_map[gid] for gid in genre_ids if gid in genre_map]
        if genre_names:
            entry.genre = genre_names[0]

        # -- Description ---------------------------------------------------
        overview: str = result.get("overview") or ""
        if overview:
            entry.description = overview

        # -- Poster --------------------------------------------------------
        poster_path: str = result.get("poster_path") or ""
        if poster_path:
            entry.image_url = f"{self.IMAGE_BASE}{poster_path}"

        log.debug(
            "TMDB enriched %r: year=%s genre=%s",
            entry.title,
            entry.year,
            entry.genre,
        )
        return entry

    def _get(
        self,
        endpoint: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """Make authenticated GET request to TMDB API.

        Returns parsed JSON or ``None`` on any failure.  Uses a single
        retry and a 10-second ceiling so TMDB hiccups don't stall the UI.
        """
        url = f"{self.BASE_URL}{endpoint}"

        merged_params: dict[str, str] = {"api_key": self._api_key}
        if params:
            merged_params.update(params)

        try:
            resp = self._http.get(url, params=merged_params, max_retries=1)
            resp.raise_for_status()
            return resp.json()
        except Exception:  # noqa: BLE001
            log.warning(
                "TMDB request failed: %s %s",
                endpoint,
                merged_params.get("query", ""),
                exc_info=True,
            )
            return None
