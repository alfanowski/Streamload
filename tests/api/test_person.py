"""Person endpoints (Pass 3 CAST-1) — bio + filmography proxies.

Both ``GET /api/person/{id}`` and ``GET /api/person/{id}/credits`` are thin
TMDB proxies. We stub ``TmdbClient.get_person`` / ``get_person_credits`` with
synthetic payloads and assert the shapes the Flutter client expects.
"""
from __future__ import annotations

import httpx
import pytest


@pytest.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "user1", "email": "user1@x.com", "password": "Hunter2!secret",
    })


# ──────────────────────────────────────────────────────────────────────────
# GET /api/person/{id} — bio
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_person_returns_bio(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_person(self, person_id):
        return {
            "id": 287,
            "name": "Brad Pitt",
            "biography": "American actor and producer.",
            "birthday": "1963-12-18",
            "deathday": None,
            "place_of_birth": "Shawnee, Oklahoma, USA",
            "profile_path": "/profile.jpg",
            "also_known_as": ["Brad", "Pitt"],
            "known_for_department": "Acting",
            "popularity": 12.5,
            # Real acting roles → profession derives back to "Acting".
            "combined_credits": {
                "cast": [
                    {"media_type": "movie", "character": "Tyler Durden"},
                    {"media_type": "movie", "character": "Rick Dalton"},
                    {"media_type": "movie", "character": "Cliff Booth"},
                ],
                "crew": [],
            },
        }

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_person",
        fake_person,
    )
    r = await api_client.get("/api/person/287")
    assert r.status_code == 200
    body = r.json()
    assert body["tmdb_id"] == 287
    assert body["name"] == "Brad Pitt"
    assert body["biography"] == "American actor and producer."
    assert body["birthday"] == "1963-12-18"
    assert body["deathday"] is None
    assert body["place_of_birth"] == "Shawnee, Oklahoma, USA"
    assert body["profile_url"] is not None
    assert body["profile_url"].endswith("/profile.jpg")
    # Larger size for the editorial hero on the person page.
    assert "/w500" in body["profile_url"]
    assert body["also_known_as"] == ["Brad", "Pitt"]
    assert body["known_for_department"] == "Acting"


@pytest.mark.asyncio
async def test_get_person_falls_back_to_english_bio(
    api_client, authed, monkeypatch,
):
    """No Italian bio → use the English translation, not a blank page."""
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_person(self, person_id):
        return {
            "id": 500,
            "name": "International Star",
            # it-IT request came back with no bio…
            "biography": "",
            "translations": {
                "translations": [
                    {"iso_639_1": "fr", "data": {"biography": "Acteur."}},
                    {"iso_639_1": "en",
                     "data": {"biography": "An acclaimed actor."}},
                ],
            },
        }

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_person",
        fake_person,
    )
    r = await api_client.get("/api/person/500")
    assert r.status_code == 200
    assert r.json()["biography"] == "An acclaimed actor."


@pytest.mark.asyncio
async def test_get_person_strips_wikipedia_attribution(
    api_client, authed, monkeypatch,
):
    """The Wikipedia CC-BY-SA footer TMDB bakes in must be cut off."""
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_person(self, person_id):
        return {
            "id": 700,
            "name": "Some Actor",
            "biography": (
                "A celebrated Italian actor known for action comedies.\n\n"
                "Description above from the Wikipedia article Some Actor, "
                "licensed under CC-BY-SA, full list of contributors on "
                "Wikipedia."
            ),
        }

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_person",
        fake_person,
    )
    r = await api_client.get("/api/person/700")
    assert r.status_code == 200
    bio = r.json()["biography"]
    assert bio == "A celebrated Italian actor known for action comedies."
    assert "Wikipedia" not in bio
    assert "CC-BY-SA" not in bio


@pytest.mark.asyncio
async def test_get_person_derives_profession_from_filmography(
    api_client, authed, monkeypatch,
):
    """A musician TMDB tags as 'Acting' but who only ever plays themselves
    gets NO profession; a real director derives 'Directing'."""
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_bieber(self, person_id):
        return {
            "id": 800,
            "name": "Justin Bieber",
            "known_for_department": "Acting",  # TMDB's mislabel
            "combined_credits": {
                "cast": [
                    {"media_type": "movie", "character": "Himself"},
                    {"media_type": "tv", "character": "Self"},
                    {"media_type": "tv", "character": "Self - Guest"},
                    {"media_type": "movie", "character": "Self"},
                ],
                "crew": [],
            },
        }

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_person", fake_bieber,
    )
    r = await api_client.get("/api/person/800")
    assert r.status_code == 200
    # Mostly "Self" → we refuse to call him an actor.
    assert r.json()["known_for_department"] is None

    async def fake_director(self, person_id):
        return {
            "id": 801,
            "name": "Some Director",
            "known_for_department": "Acting",
            "combined_credits": {
                "cast": [{"media_type": "movie", "character": "Cameo"}],
                "crew": [
                    {"media_type": "movie", "department": "Directing"},
                    {"media_type": "movie", "department": "Directing"},
                    {"media_type": "movie", "department": "Directing"},
                ],
            },
        }

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_person", fake_director,
    )
    r = await api_client.get("/api/person/801")
    assert r.status_code == 200
    assert r.json()["known_for_department"] == "Directing"


@pytest.mark.asyncio
async def test_get_person_handles_missing_optional_fields(
    api_client, authed, monkeypatch,
):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_person(self, person_id):
        return {"id": 1, "name": "Mystery"}

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_person",
        fake_person,
    )
    r = await api_client.get("/api/person/1")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Mystery"
    assert body["biography"] is None
    assert body["birthday"] is None
    assert body["deathday"] is None
    assert body["place_of_birth"] is None
    assert body["profile_url"] is None
    assert body["also_known_as"] == []
    assert body["known_for_department"] is None


@pytest.mark.asyncio
async def test_get_person_503_when_no_tmdb_key(api_client, authed, monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    r = await api_client.get("/api/person/287")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_get_person_requires_auth(api_client):
    r = await api_client.get("/api/person/287")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_person_404_returns_404(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_person(self, person_id):
        raise httpx.HTTPStatusError(
            "not found",
            request=httpx.Request("GET", "/"),
            response=httpx.Response(404),
        )

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_person",
        fake_person,
    )
    r = await api_client.get("/api/person/9999999")
    assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# GET /api/person/{id}/credits — filmography
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_person_credits_returns_sorted_filmography(
    api_client, authed, monkeypatch,
):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_credits(self, person_id):
        return {
            "cast": [
                # Lowest popularity — should sort last
                {"id": 10, "media_type": "movie", "title": "Old Indie",
                 "character": "Self", "release_date": "2001-01-01",
                 "poster_path": "/p10.jpg", "popularity": 2.0},
                # Highest popularity — should sort first
                {"id": 20, "media_type": "movie", "title": "Blockbuster",
                 "character": "Hero", "release_date": "2020-06-01",
                 "poster_path": "/p20.jpg", "popularity": 88.0},
                # Mid
                {"id": 30, "media_type": "tv", "name": "The Show",
                 "character": "Lead", "first_air_date": "2015-09-15",
                 "poster_path": "/p30.jpg", "popularity": 50.0},
            ],
            "crew": [
                # Directing credit — also surfaced
                {"id": 40, "media_type": "movie", "title": "Helmed",
                 "job": "Director", "release_date": "2018-04-04",
                 "poster_path": "/p40.jpg", "popularity": 33.0},
            ],
        }

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_person_credits",
        fake_credits,
    )
    r = await api_client.get("/api/person/287/credits")
    assert r.status_code == 200
    body = r.json()
    # Sorted desc by popularity: 88, 50, 33, 2
    assert [item["tmdb_id"] for item in body] == [20, 30, 40, 10]
    assert body[0]["title"] == "Blockbuster"
    assert body[0]["year"] == 2020
    assert body[0]["media_type"] == "movie"
    assert body[0]["poster_url"].endswith("/p20.jpg")
    assert body[0]["character"] == "Hero"
    # TV item uses `name` as title.
    tv = next(b for b in body if b["tmdb_id"] == 30)
    assert tv["title"] == "The Show"
    assert tv["year"] == 2015
    assert tv["media_type"] == "tv"


@pytest.mark.asyncio
async def test_get_person_credits_drops_talk_shows_and_ranks_leads(
    api_client, authed, monkeypatch,
):
    """Talk shows vanish; a top-billed lead outranks a popular cameo."""
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_credits(self, person_id):
        return {
            "cast": [
                # Top-billed lead in a solid film.
                {"id": 1, "media_type": "movie", "title": "Lead Role",
                 "character": "Protagonist", "order": 0,
                 "release_date": "2010-01-01", "poster_path": "/a.jpg",
                 "vote_average": 8.0, "vote_count": 5000, "popularity": 60.0},
                # Talk show — must be dropped entirely (genre 10767).
                {"id": 2, "media_type": "tv", "name": "Late Night Chat",
                 "character": "Self", "genre_ids": [10767],
                 "first_air_date": "2015-01-01", "poster_path": "/b.jpg",
                 "vote_average": 7.0, "vote_count": 200, "popularity": 120.0},
                # One-episode guest cameo — very popular, but a bit part.
                {"id": 3, "media_type": "tv", "name": "Famous Sitcom",
                 "character": "Himself", "order": 22, "episode_count": 1,
                 "first_air_date": "1999-01-01", "poster_path": "/c.jpg",
                 "vote_average": 8.5, "vote_count": 9000, "popularity": 95.0},
            ],
            "crew": [],
        }

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_person_credits",
        fake_credits,
    )
    r = await api_client.get("/api/person/287/credits")
    assert r.status_code == 200
    ids = [item["tmdb_id"] for item in r.json()]
    # Talk show gone; lead (1) ranks above the cameo (3) despite lower rating.
    assert 2 not in ids
    assert ids == [1, 3]


@pytest.mark.asyncio
async def test_get_person_credits_drops_items_without_poster(
    api_client, authed, monkeypatch,
):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_credits(self, person_id):
        return {
            "cast": [
                {"id": 1, "media_type": "movie", "title": "Has Poster",
                 "poster_path": "/p1.jpg", "popularity": 10.0,
                 "release_date": "2020-01-01"},
                {"id": 2, "media_type": "movie", "title": "No Poster",
                 "poster_path": None, "popularity": 8.0,
                 "release_date": "2020-01-01"},
                {"id": 3, "media_type": "movie",
                 "title": "★1★888★633★4176★ Why",
                 "poster_path": "/p3.jpg", "popularity": 7.0,
                 "release_date": "2020-01-01"},
            ],
            "crew": [],
        }

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_person_credits",
        fake_credits,
    )
    r = await api_client.get("/api/person/1/credits")
    assert r.status_code == 200
    body = r.json()
    titles = [item["title"] for item in body]
    # Poster-less item dropped. Spam title dropped.
    assert titles == ["Has Poster"]


@pytest.mark.asyncio
async def test_get_person_credits_deduplicates_by_tmdb_id(
    api_client, authed, monkeypatch,
):
    """An actor who also directed the same title appears twice in TMDB
    combined credits (once cast, once crew). We dedupe by ``(tmdb_id,
    media_type)`` and prefer the cast entry (it has the character field)."""
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_credits(self, person_id):
        return {
            "cast": [
                {"id": 50, "media_type": "movie", "title": "Dual Role",
                 "character": "Star", "release_date": "2019-01-01",
                 "poster_path": "/p.jpg", "popularity": 20.0},
            ],
            "crew": [
                {"id": 50, "media_type": "movie", "title": "Dual Role",
                 "job": "Director", "release_date": "2019-01-01",
                 "poster_path": "/p.jpg", "popularity": 20.0},
            ],
        }

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_person_credits",
        fake_credits,
    )
    r = await api_client.get("/api/person/50/credits")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    # Cast wins — character preserved.
    assert body[0]["character"] == "Star"


@pytest.mark.asyncio
async def test_get_person_credits_503_when_no_tmdb_key(
    api_client, authed, monkeypatch,
):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    r = await api_client.get("/api/person/287/credits")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_get_person_credits_requires_auth(api_client):
    r = await api_client.get("/api/person/287/credits")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_person_credits_404_returns_empty(
    api_client, authed, monkeypatch,
):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_credits(self, person_id):
        raise httpx.HTTPStatusError(
            "not found",
            request=httpx.Request("GET", "/"),
            response=httpx.Response(404),
        )

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_person_credits",
        fake_credits,
    )
    r = await api_client.get("/api/person/9999999/credits")
    assert r.status_code == 200
    assert r.json() == []
