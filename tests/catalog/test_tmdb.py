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
async def test_search_multi_all_parses_titles_and_people():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            {"id": 287, "media_type": "person", "name": "Brad Pitt",
             "known_for_department": "Acting", "profile_path": "/m09.jpg",
             "known_for": [
                 {"media_type": "movie", "id": 16869, "title": "Bastardi"},
                 {"media_type": "tv", "id": 1, "name": "A Show"},
             ]},
            {"id": 9, "title": "A Movie", "release_date": "2020-01-01",
             "media_type": "movie", "poster_path": "/m.jpg"},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    bundle = await client.search_multi_all("brad")
    assert len(bundle["titles"]) == 1
    assert bundle["titles"][0].media_type == "movie"
    assert len(bundle["people"]) == 1
    person = bundle["people"][0]
    assert person.tmdb_id == 287
    assert person.name == "Brad Pitt"
    assert person.known_for_department == "Acting"
    assert person.profile_url.endswith("/m09.jpg")
    assert person.known_for_titles == ["Bastardi", "A Show"]


@pytest.mark.asyncio
async def test_search_multi_all_keeps_people_without_photo_drops_noise():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            # Actor with no profile_path but a known department → kept.
            {"id": 1, "media_type": "person", "name": "No Photo Actor",
             "known_for_department": "Acting", "profile_path": None,
             "known_for": []},
            # Crew with off-list department AND no credits → dropped as noise.
            {"id": 2, "media_type": "person", "name": "Caterer",
             "known_for_department": "Crew", "profile_path": None,
             "known_for": []},
            # Off-list department but HAS credits → kept.
            {"id": 3, "media_type": "person", "name": "Sound Person",
             "known_for_department": "Sound", "profile_path": "/s.jpg",
             "known_for": [{"media_type": "movie", "title": "Loud"}]},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    bundle = await client.search_multi_all("x")
    kept = {p.tmdb_id for p in bundle["people"]}
    assert kept == {1, 3}
    no_photo = next(p for p in bundle["people"] if p.tmdb_id == 1)
    assert no_photo.profile_url is None


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
            {"id": 1, "title": "Movie One", "release_date": "2025-01-01", "poster_path": "/p.jpg"},
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
            {"id": 1, "title": "Commedia", "release_date": "2024-01-01", "poster_path": "/p.jpg"},
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
            {"id": 1, "title": "Nuovo Film", "release_date": "2025-04-01", "poster_path": "/p.jpg"},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    items = await client.new_releases(media_type="movie", days=30)
    assert len(items) == 1
    called_params = http.get.call_args.kwargs.get("params", {})
    # new_releases now sorts by popularity to avoid the date-desc spam tail
    # of fresh-upload junk on TMDB (see _is_real_title docstring).
    assert called_params.get("sort_by") == "popularity.desc"
    assert "primary_release_date.gte" in called_params


@pytest.mark.asyncio
async def test_new_releases_tv_uses_first_air_date_window():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({"results": []}))
    client = TmdbClient(api_key="x", http=http)
    await client.new_releases(media_type="tv", days=60)
    called_params = http.get.call_args.kwargs.get("params", {})
    # new_releases sorts by popularity (see test_new_releases_movie_* note).
    # The window is still TV-shaped though — first_air_date instead of
    # primary_release_date.
    assert called_params.get("sort_by") == "popularity.desc"
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


# ──────────────────────────────────────────────────────────────────────────
# Person endpoints (Pass 3 CAST-1) — bio + combined filmography. These
# return raw TMDB dicts; the API route handles shaping into PersonResponse
# and MediaSummary-style entries.
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_person_returns_raw_dict():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "id": 287,
        "name": "Brad Pitt",
        "biography": "American actor.",
        "birthday": "1963-12-18",
        "deathday": None,
        "place_of_birth": "Shawnee, Oklahoma, USA",
        "profile_path": "/profile.jpg",
        "also_known_as": ["Brad", "Pitt"],
        "known_for_department": "Acting",
        "popularity": 12.5,
    }))
    client = TmdbClient(api_key="x", http=http)
    data = await client.get_person(287)
    assert data["id"] == 287
    assert data["name"] == "Brad Pitt"
    assert data["birthday"] == "1963-12-18"
    called_url = http.get.call_args[0][0]
    assert called_url.endswith("/person/287")
    # Person endpoint asks for images via append_to_response to surface
    # additional profile photos when present.
    called_params = http.get.call_args.kwargs.get("params", {})
    assert called_params.get("append_to_response") == "images"


@pytest.mark.asyncio
async def test_get_person_credits_returns_raw_dict():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "id": 287,
        "cast": [
            {"id": 1, "media_type": "movie", "title": "Foo", "character": "Hero",
             "release_date": "2010-01-01", "poster_path": "/p.jpg", "vote_average": 7.2,
             "popularity": 30.0},
        ],
        "crew": [
            {"id": 2, "media_type": "tv", "name": "Bar", "job": "Director",
             "first_air_date": "2015-01-01", "poster_path": "/b.jpg", "vote_average": 8.0,
             "popularity": 14.0},
        ],
    }))
    client = TmdbClient(api_key="x", http=http)
    data = await client.get_person_credits(287)
    assert data["cast"][0]["title"] == "Foo"
    assert data["crew"][0]["name"] == "Bar"
    called_url = http.get.call_args[0][0]
    assert called_url.endswith("/person/287/combined_credits")
