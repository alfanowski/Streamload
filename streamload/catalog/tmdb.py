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

    async def trending_day(self, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/trending/all/day", {"page": page})
        return [self._parse_search_or_collection_item(x) for x in data.get("results", [])]

    async def trending_week(self, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/trending/all/week", {"page": page})
        return [self._parse_search_or_collection_item(x) for x in data.get("results", [])]

    async def discover_movies_by_genre(self, *, genre_ids: list[int], page: int = 1) -> list[TmdbItem]:
        data = await self._get("/discover/movie", {
            "with_genres": ",".join(str(g) for g in genre_ids),
            "sort_by": "popularity.desc",
            "page": page,
        })
        return [self._parse_movie(x) for x in data.get("results", [])]

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

    async def search_multi(self, query: str, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/search/multi", {"query": query, "page": page})
        results = []
        for x in data.get("results", []):
            mt = x.get("media_type")
            if mt not in ("movie", "tv"):
                continue
            results.append(self._parse_search_or_collection_item(x))
        return results
