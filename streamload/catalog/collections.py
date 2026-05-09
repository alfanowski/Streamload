"""TMDB collection definitions for the home page rows."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Optional

from .tmdb import TmdbClient, TmdbItem

# Each collection knows how to fetch its TmdbItems given a client.
FetchFn = Callable[[TmdbClient], Awaitable[list[TmdbItem]]]


@dataclass(frozen=True)
class CollectionDef:
    id: str
    title: str
    media_type: Optional[str]
    sort_order: int
    refresh_ttl_hours: int
    fetch: FetchFn


COLLECTION_DEFS: list[CollectionDef] = [
    CollectionDef(
        id="trending-day",
        title="Trending oggi",
        media_type=None,
        sort_order=10,
        refresh_ttl_hours=6,
        fetch=lambda c: c.trending_day(),
    ),
    CollectionDef(
        id="popular-movies",
        title="Film popolari",
        media_type="movie",
        sort_order=20,
        refresh_ttl_hours=24,
        fetch=lambda c: c.popular_movies(),
    ),
    CollectionDef(
        id="popular-tv",
        title="Serie TV popolari",
        media_type="tv",
        sort_order=30,
        refresh_ttl_hours=24,
        fetch=lambda c: c.popular_tv(),
    ),
    CollectionDef(
        id="anime-season",
        title="Anime di stagione",
        media_type="tv",
        sort_order=40,
        refresh_ttl_hours=24,
        fetch=lambda c: c.discover_anime(),
    ),
    CollectionDef(
        id="top-rated-all-time",
        title="Top rated di sempre",
        media_type="movie",
        sort_order=50,
        refresh_ttl_hours=168,  # weekly
        fetch=lambda c: c.top_rated_movies(),
    ),
    CollectionDef(
        id="genre-action",
        title="Azione",
        media_type="movie",
        sort_order=60,
        refresh_ttl_hours=24,
        fetch=lambda c: c.discover_movies_by_genre(genre_ids=[28]),
    ),
    CollectionDef(
        id="genre-horror",
        title="Horror",
        media_type="movie",
        sort_order=70,
        refresh_ttl_hours=24,
        fetch=lambda c: c.discover_movies_by_genre(genre_ids=[27]),
    ),
    CollectionDef(
        id="genre-scifi",
        title="Sci-Fi & Fantasy",
        media_type="movie",
        sort_order=80,
        refresh_ttl_hours=24,
        fetch=lambda c: c.discover_movies_by_genre(genre_ids=[878, 14]),
    ),
]


def get_collection_def(id: str) -> Optional[CollectionDef]:
    for d in COLLECTION_DEFS:
        if d.id == id:
            return d
    return None
