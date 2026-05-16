"""Async TMDB v3 client.

Returns typed ``TmdbItem`` dataclasses. Localized to ``it-IT`` by default
(can be overridden per call). Image URLs are pre-built with the default
``w500`` size — caller can switch via ``image_url(path, size=...)``.

Rate limit: TMDB allows 40 req/sec for free tier — way more than we need.
We don't add explicit throttling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from streamload.utils.logger import get_logger

log = get_logger(__name__)

_BASE = "https://api.themoviedb.org/3"
_IMG_BASE = "https://image.tmdb.org/t/p"


@dataclass
class TmdbItem:
    tmdb_id: int
    media_type: str  # 'movie' | 'tv'
    title: str
    original_title: Optional[str] = None
    year: Optional[int] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    overview: Optional[str] = None
    rating: Optional[float] = None
    runtime_minutes: Optional[int] = None
    seasons_count: Optional[int] = None
    genres: list[str] = field(default_factory=list)


def _parse_year(date_str: Optional[str]) -> Optional[int]:
    if not date_str or len(date_str) < 4:
        return None
    try:
        return int(date_str[:4])
    except ValueError:
        return None


class TmdbClient:
    """Async TMDB v3 API client."""

    def __init__(self, *, api_key: str, http: Any, language: str = "it-IT", region: str = "IT") -> None:
        self._api_key = api_key
        self._http = http
        self._lang = language
        self._region = region

    def image_url(self, path: Optional[str], *, size: str = "w500") -> Optional[str]:
        if not path:
            return None
        return f"{_IMG_BASE}/{size}{path}"

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        params = params or {}
        params.setdefault("api_key", self._api_key)
        params.setdefault("language", self._lang)
        params.setdefault("region", self._region)
        url = f"{_BASE}{path}"
        resp = await self._http.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _parse_movie(self, data: dict) -> TmdbItem:
        return TmdbItem(
            tmdb_id=int(data["id"]),
            media_type="movie",
            title=data.get("title") or data.get("original_title") or "",
            original_title=data.get("original_title"),
            year=_parse_year(data.get("release_date")),
            poster_url=self.image_url(data.get("poster_path")),
            backdrop_url=self.image_url(data.get("backdrop_path"), size="w1280"),
            overview=data.get("overview") or None,
            rating=float(data["vote_average"]) if data.get("vote_average") is not None else None,
            runtime_minutes=data.get("runtime"),
            genres=[g["name"] for g in data.get("genres", [])] if "genres" in data else [],
        )

    def _parse_tv(self, data: dict) -> TmdbItem:
        return TmdbItem(
            tmdb_id=int(data["id"]),
            media_type="tv",
            title=data.get("name") or data.get("original_name") or "",
            original_title=data.get("original_name"),
            year=_parse_year(data.get("first_air_date")),
            poster_url=self.image_url(data.get("poster_path")),
            backdrop_url=self.image_url(data.get("backdrop_path"), size="w1280"),
            overview=data.get("overview") or None,
            rating=float(data["vote_average"]) if data.get("vote_average") is not None else None,
            seasons_count=data.get("number_of_seasons"),
            genres=[g["name"] for g in data.get("genres", [])] if "genres" in data else [],
        )

    def _parse_search_or_collection_item(self, data: dict, default_type: str = "movie") -> TmdbItem:
        # `media_type` is only present in /search/multi and /trending responses.
        # Otherwise we assume default_type from the endpoint.
        mt = data.get("media_type", default_type)
        if mt == "tv":
            return self._parse_tv(data)
        return self._parse_movie(data)

    async def popular_movies(self, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/movie/popular", {"page": page})
        return [self._parse_movie(x) for x in data.get("results", [])]

    async def popular_tv(self, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/tv/popular", {"page": page})
        return [self._parse_tv(x) for x in data.get("results", [])]

    async def top_rated_movies(self, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/movie/top_rated", {"page": page})
        return [self._parse_movie(x) for x in data.get("results", [])]

    async def top_rated_tv(self, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/tv/top_rated", {"page": page})
        return [self._parse_tv(x) for x in data.get("results", [])]

    async def trending_day(self, *, media_type: str = "all", page: int = 1) -> list[TmdbItem]:
        """``media_type`` is one of ``all``/``movie``/``tv``."""
        data = await self._get(f"/trending/{media_type}/day", {"page": page})
        default = "tv" if media_type == "tv" else "movie"
        return [
            self._parse_search_or_collection_item(x, default_type=default)
            for x in data.get("results", [])
        ]

    async def trending_week(self, *, media_type: str = "all", page: int = 1) -> list[TmdbItem]:
        data = await self._get(f"/trending/{media_type}/week", {"page": page})
        default = "tv" if media_type == "tv" else "movie"
        return [
            self._parse_search_or_collection_item(x, default_type=default)
            for x in data.get("results", [])
        ]

    async def discover_movies_by_genre(self, *, genre_ids: list[int], page: int = 1) -> list[TmdbItem]:
        data = await self._get("/discover/movie", {
            "with_genres": ",".join(str(g) for g in genre_ids),
            "sort_by": "popularity.desc",
            "page": page,
        })
        return [self._parse_movie(x) for x in data.get("results", [])]

    async def discover_by_genre(
        self,
        *,
        genre_ids: list[int],
        media_type: str,
        original_language: str | None = None,
        page: int = 1,
    ) -> list[TmdbItem]:
        """Discover ``movie`` or ``tv`` items filtered by genre IDs.

        Optional ``original_language`` lets Home rows like "Commedie italiane"
        constrain results to a specific language (``it``).
        """
        if media_type not in ("movie", "tv"):
            raise ValueError("media_type must be 'movie' or 'tv'")
        params: dict[str, Any] = {
            "with_genres": ",".join(str(g) for g in genre_ids),
            "sort_by": "popularity.desc",
            "page": page,
        }
        if original_language:
            params["with_original_language"] = original_language
        data = await self._get(f"/discover/{media_type}", params)
        parser = self._parse_movie if media_type == "movie" else self._parse_tv
        return [parser(x) for x in data.get("results", [])]

    async def new_releases(
        self,
        *,
        media_type: str,
        days: int = 60,
        page: int = 1,
    ) -> list[TmdbItem]:
        """Recent releases sorted by date — the last ``days`` days.

        Movies use ``primary_release_date``; TV uses ``first_air_date``. The
        TMDB API requires the ``.gte`` / ``.lte`` window to narrow "new" to a
        believable window — without it we get every movie ever made sorted by
        release date, which means a bunch of 1900s shorts at the top.
        """
        if media_type not in ("movie", "tv"):
            raise ValueError("media_type must be 'movie' or 'tv'")
        from datetime import UTC, datetime, timedelta

        today = datetime.now(UTC).date()
        floor = today - timedelta(days=days)
        if media_type == "movie":
            params: dict[str, Any] = {
                "sort_by": "primary_release_date.desc",
                "primary_release_date.gte": floor.isoformat(),
                "primary_release_date.lte": today.isoformat(),
                "page": page,
            }
        else:
            params = {
                "sort_by": "first_air_date.desc",
                "first_air_date.gte": floor.isoformat(),
                "first_air_date.lte": today.isoformat(),
                "page": page,
            }
        data = await self._get(f"/discover/{media_type}", params)
        parser = self._parse_movie if media_type == "movie" else self._parse_tv
        return [parser(x) for x in data.get("results", [])]

    async def similar(self, tmdb_id: int, *, media_type: str, page: int = 1) -> list[TmdbItem]:
        if media_type not in ("movie", "tv"):
            raise ValueError("media_type must be 'movie' or 'tv'")
        data = await self._get(f"/{media_type}/{tmdb_id}/similar", {"page": page})
        parser = self._parse_movie if media_type == "movie" else self._parse_tv
        return [parser(x) for x in data.get("results", [])]

    async def recommendations(self, tmdb_id: int, *, media_type: str, page: int = 1) -> list[TmdbItem]:
        if media_type not in ("movie", "tv"):
            raise ValueError("media_type must be 'movie' or 'tv'")
        data = await self._get(f"/{media_type}/{tmdb_id}/recommendations", {"page": page})
        parser = self._parse_movie if media_type == "movie" else self._parse_tv
        return [parser(x) for x in data.get("results", [])]

    async def discover_anime(self, *, page: int = 1) -> list[TmdbItem]:
        # Anime: TV with genre 16 (Animation) + origin country JP.
        data = await self._get("/discover/tv", {
            "with_genres": "16",
            "with_origin_country": "JP",
            "sort_by": "popularity.desc",
            "page": page,
        })
        return [self._parse_tv(x) for x in data.get("results", [])]

    async def get_movie(self, tmdb_id: int) -> TmdbItem:
        data = await self._get(f"/movie/{tmdb_id}")
        return self._parse_movie(data)

    async def get_tv(self, tmdb_id: int) -> TmdbItem:
        data = await self._get(f"/tv/{tmdb_id}")
        return self._parse_tv(data)

    async def get_tv_season(self, tmdb_id: int, season_number: int) -> dict:
        """Raw season payload — caller picks the fields it cares about."""
        return await self._get(f"/tv/{tmdb_id}/season/{season_number}")

    async def get_videos(self, tmdb_id: int, *, media_type: str) -> list[dict]:
        """Raw videos payload (``results`` array) for movie or tv.

        We do NOT localise this call — many titles only have an English
        trailer registered, and asking TMDB for ``it-IT`` returns an empty
        list. Callers can filter by ``site`` / ``type`` / ``official``.
        """
        data = await self._get(
            f"/{media_type}/{tmdb_id}/videos",
            {"language": "en-US"},
        )
        return list(data.get("results", []))

    async def get_credits(self, tmdb_id: int, *, media_type: str) -> dict:
        """Raw credits payload (``cast`` + ``crew`` arrays) for movie or tv.

        Localised to the client's default (``it-IT``) so character names
        come back in Italian when TMDB has them. Callers are expected to
        cap ``cast`` and filter ``crew`` to the jobs they care about.
        """
        return await self._get(f"/{media_type}/{tmdb_id}/credits")

    async def search_multi(self, query: str, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/search/multi", {"query": query, "page": page})
        results = []
        for x in data.get("results", []):
            mt = x.get("media_type")
            if mt not in ("movie", "tv"):
                continue
            results.append(self._parse_search_or_collection_item(x))
        return results
