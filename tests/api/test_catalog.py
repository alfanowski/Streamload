import os
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem


@pytest.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "user1", "email": "user1@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_get_catalog_item(api_client, authed):
    async for db in gs():
        db.add(CatalogItem(tmdb_id=42, media_type="movie", title="Foo", year=2024))
        await db.commit()
        break
    r = await api_client.get("/api/catalog/42?media_type=movie")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Foo"
    # v3: server never knows sources — they live in the client.
    assert body["sources"] == []


@pytest.mark.asyncio
async def test_get_catalog_item_404(api_client, authed):
    r = await api_client.get("/api/catalog/9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_catalog_requires_auth(api_client):
    r = await api_client.get("/api/catalog/42")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_videos_filters_to_youtube(api_client, authed, monkeypatch):
    """The endpoint returns only YouTube results and strips non-YouTube sites."""
    from unittest.mock import AsyncMock

    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_get_videos(self, tmdb_id, *, media_type):
        return [
            {"key": "yt1", "site": "YouTube", "type": "Trailer", "official": True, "name": "Main"},
            {"key": "vm1", "site": "Vimeo", "type": "Trailer", "official": True, "name": "Skip"},
            {"key": "yt2", "site": "YouTube", "type": "Teaser", "official": False, "name": "Teaser"},
        ]

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_videos",
        fake_get_videos,
    )
    r = await api_client.get("/api/catalog/1396/videos?media_type=tv")
    assert r.status_code == 200
    body = r.json()
    assert [v["key"] for v in body] == ["yt1", "yt2"]
    assert all(v["site"] == "YouTube" for v in body)


@pytest.mark.asyncio
async def test_get_videos_bad_media_type_400(api_client, authed):
    r = await api_client.get("/api/catalog/1396/videos?media_type=bogus")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_get_videos_requires_auth(api_client):
    r = await api_client.get("/api/catalog/1396/videos?media_type=movie")
    assert r.status_code == 401


# ──────────────────────────────────────────────────────────────────────────
# Credits endpoint (sub-plan 8 / Phase E2). Backend caps cast at 10 (by
# `order`) and filters crew to {Creator, Director, Showrunner, Producer,
# Writer}. Tests stub TmdbClient.get_credits with a synthetic payload.
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_credits_caps_cast_and_filters_crew(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_credits(self, tmdb_id, *, media_type):
        return {
            "cast": [
                # 12 cast entries — endpoint should cap at 10 and sort by order
                {"id": i, "name": f"Actor {i}", "character": f"Char {i}",
                 "order": i, "profile_path": f"/p{i}.jpg"}
                for i in range(12)
            ],
            "crew": [
                {"id": 100, "name": "A Director", "job": "Director",
                 "profile_path": "/d.jpg"},
                {"id": 101, "name": "B Writer", "job": "Writer", "profile_path": None},
                {"id": 102, "name": "C Editor", "job": "Editor"},        # skipped
                {"id": 103, "name": "D Creator", "job": "Creator"},
                {"id": 100, "name": "A Director", "job": "Director"},    # dedup
                {"id": 104, "name": "E Producer", "job": "Producer"},
            ],
        }

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_credits",
        fake_credits,
    )
    r = await api_client.get("/api/catalog/1396/credits?media_type=tv")
    assert r.status_code == 200
    body = r.json()
    assert len(body["cast"]) == 10
    assert body["cast"][0]["name"] == "Actor 0"
    assert body["cast"][0]["character"] == "Char 0"
    # Profile URL is a full TMDB image URL.
    assert body["cast"][0]["profile_url"].startswith("https://image.tmdb.org/t/p/w185")

    crew_jobs = [c["job"] for c in body["crew"]]
    assert "Editor" not in crew_jobs
    assert "Director" in crew_jobs
    assert "Creator" in crew_jobs
    assert "Producer" in crew_jobs
    # Dedup: A Director only appears once.
    assert crew_jobs.count("Director") == 1


@pytest.mark.asyncio
async def test_get_credits_bad_media_type_400(api_client, authed):
    r = await api_client.get("/api/catalog/1396/credits?media_type=bogus")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_get_credits_requires_auth(api_client):
    r = await api_client.get("/api/catalog/1396/credits?media_type=movie")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_credits_404_returns_empty(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_credits(self, tmdb_id, *, media_type):
        raise httpx.HTTPStatusError(
            "not found",
            request=httpx.Request("GET", "/"),
            response=httpx.Response(404),
        )

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.get_credits",
        fake_credits,
    )
    r = await api_client.get("/api/catalog/1/credits?media_type=movie")
    assert r.status_code == 200
    assert r.json() == {"cast": [], "crew": []}


# ──────────────────────────────────────────────────────────────────────────
# Home rows (sub-plan 8 / Phase D1) — TMDB-proxy endpoints fed to the
# client's PosterRow / BackdropRow components. Each test stubs the
# corresponding TmdbClient method and asserts the shape that the client's
# MediaSummary expects (tmdb_id / media_type / title / year / poster_url /
# backdrop_url). We also exercise validation (bad media_type / missing key).
# ──────────────────────────────────────────────────────────────────────────


def _summary_item(**overrides):
    """Build a synthetic TmdbItem with sensible defaults for row tests."""
    from streamload.catalog.tmdb import TmdbItem

    base = dict(
        tmdb_id=1,
        media_type="movie",
        title="Foo",
        year=2025,
        poster_url="https://i/p.jpg",
        backdrop_url="https://i/b.jpg",
    )
    base.update(overrides)
    return TmdbItem(**base)


@pytest.mark.asyncio
async def test_rows_trending_week_default(api_client, authed, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_week(self, *, media_type="all", page=1):
        return [
            _summary_item(tmdb_id=10, title="A"),
            _summary_item(tmdb_id=11, media_type="tv", title="B", year=2024),
        ]

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.trending_week", fake_week,
    )
    r = await api_client.get("/api/catalog/rows/trending")
    assert r.status_code == 200
    body = r.json()
    assert [b["tmdb_id"] for b in body] == [10, 11]
    assert body[0]["title"] == "A"
    assert body[0]["poster_url"] == "https://i/p.jpg"
    assert body[1]["media_type"] == "tv"


@pytest.mark.asyncio
async def test_rows_trending_day(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_day(self, *, media_type="all", page=1):
        # Echo media_type back so we can assert the route forwarded it.
        return [_summary_item(tmdb_id=1, media_type=media_type, title=f"mt={media_type}")]

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.trending_day", fake_day,
    )
    r = await api_client.get("/api/catalog/rows/trending?period=day&media_type=movie")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["title"] == "mt=movie"


@pytest.mark.asyncio
async def test_rows_trending_invalid_period(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    r = await api_client.get("/api/catalog/rows/trending?period=hour")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_rows_trending_503_when_no_tmdb_key(api_client, authed, monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    r = await api_client.get("/api/catalog/rows/trending")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_rows_new_releases_movie(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_new(self, *, media_type, days=60, page=1):
        return [_summary_item(tmdb_id=100, media_type=media_type, title=f"new-{media_type}")]

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.new_releases", fake_new,
    )
    r = await api_client.get("/api/catalog/rows/new-releases?media_type=movie")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["title"] == "new-movie"


@pytest.mark.asyncio
async def test_rows_new_releases_bad_media_type(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    r = await api_client.get("/api/catalog/rows/new-releases?media_type=bogus")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_rows_by_genre(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    captured: dict = {}

    async def fake_disc(self, *, genre_ids, media_type, original_language=None, page=1):
        captured["ids"] = genre_ids
        captured["media_type"] = media_type
        captured["lang"] = original_language
        return [_summary_item(tmdb_id=g, title=f"g{g}") for g in genre_ids]

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.discover_by_genre", fake_disc,
    )
    r = await api_client.get(
        "/api/catalog/rows/by-genre?genre_ids=80,53&media_type=movie&original_language=it",
    )
    assert r.status_code == 200
    body = r.json()
    assert [b["title"] for b in body] == ["g80", "g53"]
    assert captured["ids"] == [80, 53]
    assert captured["media_type"] == "movie"
    assert captured["lang"] == "it"


@pytest.mark.asyncio
async def test_rows_by_genre_missing_ids(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    r = await api_client.get(
        "/api/catalog/rows/by-genre?genre_ids=&media_type=movie",
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_rows_top_rated_tv(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_top(self, *, page=1):
        return [_summary_item(tmdb_id=7, media_type="tv", title="GOAT")]

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.top_rated_tv", fake_top,
    )
    r = await api_client.get("/api/catalog/rows/top-rated?media_type=tv")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["title"] == "GOAT"
    assert body[0]["media_type"] == "tv"


@pytest.mark.asyncio
async def test_rows_similar_endpoint(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_similar(self, tmdb_id, *, media_type, page=1):
        return [_summary_item(tmdb_id=tmdb_id + 1, media_type=media_type, title="like")]

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.similar", fake_similar,
    )
    r = await api_client.get("/api/catalog/1396/similar?media_type=tv")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["tmdb_id"] == 1397
    assert body[0]["media_type"] == "tv"


@pytest.mark.asyncio
async def test_rows_recommendations_endpoint(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_recs(self, tmdb_id, *, media_type, page=1):
        return [_summary_item(tmdb_id=42, media_type=media_type, title="rec")]

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.recommendations", fake_recs,
    )
    r = await api_client.get("/api/catalog/1396/recommendations?media_type=movie")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["title"] == "rec"


@pytest.mark.asyncio
async def test_rows_caps_at_20(api_client, authed, monkeypatch):
    """Each row endpoint should cap at 20 items even when TMDB returns more."""
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    async def fake_week(self, *, media_type="all", page=1):
        return [_summary_item(tmdb_id=i, title=f"t{i}") for i in range(50)]

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.trending_week", fake_week,
    )
    r = await api_client.get("/api/catalog/rows/trending")
    assert r.status_code == 200
    assert len(r.json()) == 20


@pytest.mark.asyncio
async def test_rows_require_auth(api_client):
    r = await api_client.get("/api/catalog/rows/trending")
    assert r.status_code == 401
