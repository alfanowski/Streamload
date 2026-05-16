"""TMDB v3 API client (mocked)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from streamload.catalog.tmdb import TmdbClient, TmdbItem


def _mk_resp(json_payload: dict, status: int = 200):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=json_payload)
    r.raise_for_status = MagicMock()
    return r


@pytest.mark.asyncio
async def test_popular_movies_parses_response():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            {"id": 100, "title": "Foo", "release_date": "2024-05-01",
             "poster_path": "/p.jpg", "backdrop_path": "/b.jpg",
             "overview": "ovv", "vote_average": 7.5, "genre_ids": [28, 12]},
        ],
        "total_results": 1,
    }))
    client = TmdbClient(api_key="x", http=http)
    items = await client.popular_movies()
    assert len(items) == 1
    assert isinstance(items[0], TmdbItem)
    assert items[0].tmdb_id == 100
    assert items[0].title == "Foo"
    assert items[0].year == 2024
    assert items[0].poster_url.endswith("/p.jpg")


@pytest.mark.asyncio
async def test_trending_includes_media_type():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            {"id": 5, "name": "Show", "first_air_date": "2023-01-01",
             "media_type": "tv", "poster_path": "/x.jpg"},
            {"id": 6, "title": "Movie", "release_date": "2024-01-01",
             "media_type": "movie", "poster_path": "/y.jpg"},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    items = await client.trending_day()
    types = {i.media_type for i in items}
    assert types == {"movie", "tv"}


@pytest.mark.asyncio
async def test_get_movie_details():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "id": 100, "title": "Foo", "release_date": "2024-05-01",
        "poster_path": "/p.jpg", "overview": "long plot",
        "runtime": 138, "vote_average": 8.0,
        "genres": [{"id": 28, "name": "Action"}],
    }))
    client = TmdbClient(api_key="x", http=http)
    item = await client.get_movie(100)
    assert item.runtime_minutes == 138
    assert "Action" in item.genres


@pytest.mark.asyncio
async def test_search_returns_typed_items():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            {"id": 9, "title": "M", "release_date": "2020-01-01",
             "media_type": "movie", "poster_path": "/m.jpg"},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    items = await client.search_multi("M")
    assert len(items) == 1
    assert items[0].media_type == "movie"


@pytest.mark.asyncio
async def test_image_url_uses_w500_default():
    http = MagicMock()
    client = TmdbClient(api_key="x", http=http)
    url = client.image_url("/abc.jpg")
    assert url == "https://image.tmdb.org/t/p/w500/abc.jpg"
    url_xl = client.image_url("/abc.jpg", size="w780")
    assert url_xl == "https://image.tmdb.org/t/p/w780/abc.jpg"


@pytest.mark.asyncio
async def test_image_url_returns_none_for_none():
    http = MagicMock()
    client = TmdbClient(api_key="x", http=http)
    assert client.image_url(None) is None


@pytest.mark.asyncio
async def test_trending_day_with_media_type_filter():
    """``media_type=movie`` should hit ``/trending/movie/day`` rather than
    ``/trending/all/day``, and parse the rows as movies by default (TMDB does
    not include ``media_type`` in filtered responses)."""
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            {"id": 1, "title": "M", "release_date": "2025-01-01", "poster_path": "/p.jpg"},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    items = await client.trending_day(media_type="movie")
    assert items[0].media_type == "movie"
    called_url = http.get.call_args[0][0]
    assert "/trending/movie/day" in called_url


@pytest.mark.asyncio
async def test_discover_by_genre_movie_with_language():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            {"id": 1, "title": "C", "release_date": "2024-01-01", "poster_path": "/p.jpg"},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    items = await client.discover_by_genre(
        genre_ids=[35], media_type="movie", original_language="it",
    )
    assert len(items) == 1
    called_params = http.get.call_args.kwargs.get("params", {})
    assert called_params.get("with_genres") == "35"
    assert called_params.get("with_original_language") == "it"


@pytest.mark.asyncio
async def test_new_releases_movie_uses_release_date_window():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            {"id": 1, "title": "N", "release_date": "2025-04-01", "poster_path": "/p.jpg"},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    items = await client.new_releases(media_type="movie", days=30)
    assert len(items) == 1
    called_params = http.get.call_args.kwargs.get("params", {})
    assert called_params.get("sort_by") == "primary_release_date.desc"
    assert "primary_release_date.gte" in called_params


@pytest.mark.asyncio
async def test_new_releases_tv_uses_first_air_date_window():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({"results": []}))
    client = TmdbClient(api_key="x", http=http)
    await client.new_releases(media_type="tv", days=60)
    called_params = http.get.call_args.kwargs.get("params", {})
    assert called_params.get("sort_by") == "first_air_date.desc"
    assert "first_air_date.gte" in called_params


@pytest.mark.asyncio
async def test_similar_and_recommendations_validate_media_type():
    http = MagicMock()
    client = TmdbClient(api_key="x", http=http)
    with pytest.raises(ValueError):
        await client.similar(1, media_type="weird")
    with pytest.raises(ValueError):
        await client.recommendations(1, media_type="weird")


@pytest.mark.asyncio
async def test_top_rated_tv_endpoint():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            {"id": 1, "name": "Show", "first_air_date": "2010-01-01",
             "poster_path": "/p.jpg"},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    items = await client.top_rated_tv()
    assert items[0].media_type == "tv"
    called_url = http.get.call_args[0][0]
    assert called_url.endswith("/tv/top_rated")
