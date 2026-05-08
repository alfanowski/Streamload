# Streamload v2 — Plan 2: Catalog + Source Ranker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the TMDB-driven canonical catalog with reverse-lookup to all 13 v1 service adapters. By the end, the API exposes `/api/collections`, `/api/catalog/{tmdb_id}`, `/api/search` returning ranked sources for each title. A background worker refreshes TMDB collections on schedule.

**Architecture:** New `streamload/catalog/` package wraps a typed TMDB client, a fuzzy title matcher, an async ingestion orchestrator, and a source ranker. Catalog state lives in 5 new Postgres tables. Existing v1 service plugins are reused unchanged for their `search()` methods. A background `granian` worker process (separate from the API) periodically refreshes collections.

**Tech Stack:** Python 3.11+ async, httpx async, SQLAlchemy 2.x, asyncio.Semaphore for parallel reverse lookups, rapidfuzz for title matching.

**Spec reference:** `docs/superpowers/specs/2026-05-08-streamload-v2-design.md` §6.1 (Catalog), §6.2 (Source Ranker), §5.1 (Catalog tables).

**Prerequisite:** Plan 1 merged into main.

---

## File Structure

**New package — `streamload/catalog/`:**
- `__init__.py` — re-exports
- `tmdb.py` — typed TMDB v3 API client (popular, trending, top-rated, search, details, by-genre)
- `match.py` — title normalization + fuzzy match (rapidfuzz)
- `collections.py` — collection definitions (id → TMDB endpoint mapping)
- `ingest.py` — orchestrator: TMDB fetch → metadata upsert → reverse-lookup → collection_items rebuild
- `ranker.py` — score sources using §6.2 weights, return ranked list with "Server N" labels
- `service.py` — facade: `get_item(tmdb_id)`, `get_collection(id)`, `search(query)`
- `worker.py` — standalone async loop for periodic refresh (entry point for systemd/Docker)

**Modified files:**
- `streamload/db/models.py` — add `CatalogItem`, `CatalogSource`, `Collection`, `CollectionItem`, `TvEpisode` ORM models
- `streamload/services/base.py` — add `async def search_async(self, query: str) -> list[MediaEntry]` (default impl wraps `search()` in `asyncio.to_thread`)
- `streamload/api/app.py` — include catalog/collections/search routers
- `streamload/utils/config.py` — extend with `tmdb` + `catalog` sections (already noted as placeholder in Plan 1)
- `streamload/utils/logger.py` — no change, but ensure used in new modules
- `requirements.txt` — add `rapidfuzz>=3.10`
- `migrations/versions/0002_catalog.py` — new migration

**New API routes — `streamload/api/routes/`:**
- `catalog.py` — `GET /api/catalog/{tmdb_id}` (item + ranked sources), `POST /api/admin/catalog/refresh/{collection_id}`
- `collections.py` — `GET /api/collections` (list), `GET /api/collections/{id}` (items)
- `search.py` — `GET /api/search?q=...` (live TMDB search + reverse lookup)

**New tests — `tests/catalog/`:**
- `__init__.py`
- `test_tmdb.py` — mocked TMDB API responses
- `test_match.py` — title normalization + fuzzy match unit tests
- `test_ingest.py` — orchestrator (mocked TMDB + mocked services)
- `test_ranker.py` — score weights + tie-breaking
- `test_service.py` — facade integration

**New API tests — `tests/api/`:**
- `test_catalog.py`
- `test_collections.py`
- `test_search.py`

---

## Conventions

- Conventional commits (`feat:`, `test:`, etc.). **NO `Co-Authored-By` trailers.**
- TDD strict.
- `venv/bin/pytest` only.
- Branch: `feat/v2-catalog-ranker` from main.
- All new code is async-first.
- TMDB API key read from `RESEND_API_KEY`-style env var: `TMDB_API_KEY`. Tests mock the client, no real API calls.

---

## Task 0: Branch + dependencies

- [ ] Create branch:

```bash
git checkout main && git pull
git checkout -b feat/v2-catalog-ranker
```

- [ ] Add to `requirements.txt`:

```
rapidfuzz>=3.10
```

- [ ] Install:

```bash
venv/bin/pip install -r requirements.txt
```

- [ ] Commit:

```bash
git add requirements.txt
git commit -m "chore: add rapidfuzz for title matching"
```

---

## Task 1: Catalog ORM models + migration

**Files:**
- Modify: `streamload/db/models.py`
- Create: `migrations/versions/0002_catalog_schema.py` (auto-generated, then manually verified)
- Create: `tests/db/test_catalog_models.py`

- [ ] **Step 1: Failing test**

`tests/db/test_catalog_models.py`:
```python
from streamload.db.models import (
    CatalogItem, CatalogSource, Collection, CollectionItem, TvEpisode,
)


def test_catalog_item_columns():
    cols = {c.name for c in CatalogItem.__table__.columns}
    assert {"tmdb_id", "media_type", "title", "original_title", "year",
            "poster_url", "backdrop_url", "overview", "rating",
            "runtime_minutes", "seasons_count", "genres",
            "metadata_fetched_at"} <= cols


def test_catalog_source_pk():
    pk = {c.name for c in CatalogSource.__table__.primary_key.columns}
    assert pk == {"tmdb_id", "service_short_name"}


def test_collection_columns():
    cols = {c.name for c in Collection.__table__.columns}
    assert {"id", "title", "media_type", "sort_order",
            "refresh_ttl_hours", "last_refreshed_at"} <= cols


def test_collection_item_pk():
    pk = {c.name for c in CollectionItem.__table__.primary_key.columns}
    assert pk == {"collection_id", "tmdb_id"}


def test_tv_episode_pk():
    pk = {c.name for c in TvEpisode.__table__.primary_key.columns}
    assert pk == {"tmdb_id", "season_number", "episode_number"}
```

- [ ] **Step 2: Run, expect FAIL**

```bash
venv/bin/pytest tests/db/test_catalog_models.py -v
```

- [ ] **Step 3: Append to `streamload/db/models.py`**

```python
from sqlalchemy import Date, Numeric


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    original_title: Mapped[Optional[str]] = mapped_column(Text)
    year: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    poster_url: Mapped[Optional[str]] = mapped_column(Text)
    backdrop_url: Mapped[Optional[str]] = mapped_column(Text)
    overview: Mapped[Optional[str]] = mapped_column(Text)
    rating: Mapped[Optional[float]] = mapped_column(Numeric(3, 1))
    runtime_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    seasons_count: Mapped[Optional[int]] = mapped_column(Integer)
    genres: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default="{}")
    metadata_fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    sources: Mapped[list["CatalogSource"]] = relationship(
        back_populates="item", cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("media_type IN ('movie', 'tv')", name="ck_catalog_items_media_type"),
    )


class CatalogSource(Base):
    __tablename__ = "catalog_sources"

    tmdb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("catalog_items.tmdb_id", ondelete="CASCADE"), primary_key=True,
    )
    service_short_name: Mapped[str] = mapped_column(Text, primary_key=True, index=True)
    service_url: Mapped[str] = mapped_column(Text, nullable=False)
    service_media_id: Mapped[str] = mapped_column(Text, nullable=False)
    quality_max_height: Mapped[Optional[int]] = mapped_column(Integer)
    languages_audio: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default="{}")
    languages_subs: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default="{}")
    last_verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    item: Mapped[CatalogItem] = relationship(back_populates="sources")


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[Optional[str]] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    refresh_ttl_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24, server_default="24")
    last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["CollectionItem"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan",
    )


class CollectionItem(Base):
    __tablename__ = "collection_items"

    collection_id: Mapped[str] = mapped_column(
        Text, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True,
    )
    tmdb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("catalog_items.tmdb_id", ondelete="CASCADE"), primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    collection: Mapped[Collection] = relationship(back_populates="items")


class TvEpisode(Base):
    __tablename__ = "tv_episodes"

    tmdb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("catalog_items.tmdb_id", ondelete="CASCADE"), primary_key=True,
    )
    season_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(Text)
    overview: Mapped[Optional[str]] = mapped_column(Text)
    air_date: Mapped[Optional[Date]] = mapped_column(Date)
    runtime_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    still_url: Mapped[Optional[str]] = mapped_column(Text)
```

- [ ] **Step 4: Run, expect PASS**

```bash
venv/bin/pytest tests/db/test_catalog_models.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Generate + apply migration**

```bash
DATABASE_URL=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload \
  venv/bin/alembic revision --autogenerate -m "catalog schema"
```

Rename file to `0002_catalog_schema.py`. Inspect it: should create the 5 tables + indexes.

```bash
DATABASE_URL=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload \
  venv/bin/alembic upgrade head
```

Verify:
```bash
psql streamload -c "\dt" | grep -E "catalog|collection|tv_episodes"
```
Expected: 5 new tables listed.

- [ ] **Step 6: Commit**

```bash
git add streamload/db/models.py migrations/versions/0002_catalog_schema.py tests/db/test_catalog_models.py
git commit -m "feat(db): catalog schema (5 tables + migration)"
```

---

## Task 2: TMDB client

**Files:**
- Create: `streamload/catalog/__init__.py`
- Create: `streamload/catalog/tmdb.py`
- Create: `tests/catalog/__init__.py`
- Create: `tests/catalog/test_tmdb.py`

- [ ] **Step 1: Failing test**

`tests/catalog/test_tmdb.py`:
```python
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
```

- [ ] **Step 2: Run, expect FAIL**

```bash
venv/bin/pytest tests/catalog/test_tmdb.py -v
```

- [ ] **Step 3: Implement `streamload/catalog/__init__.py`**

```python
"""Catalog package — TMDB-driven aggregator."""
from __future__ import annotations
```

- [ ] **Step 4: Implement `streamload/catalog/tmdb.py`**

```python
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
```

- [ ] **Step 5: Run, expect PASS**

```bash
venv/bin/pytest tests/catalog/test_tmdb.py -v
```
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add streamload/catalog/__init__.py streamload/catalog/tmdb.py tests/catalog/__init__.py tests/catalog/test_tmdb.py
git commit -m "feat(catalog): typed async TMDB v3 client"
```

---

## Task 3: Title matcher

**Files:**
- Create: `streamload/catalog/match.py`
- Create: `tests/catalog/test_match.py`

- [ ] **Step 1: Failing test**

`tests/catalog/test_match.py`:
```python
"""Title normalization + fuzzy match."""
from streamload.catalog.match import (
    best_match,
    normalize_title,
    title_similarity,
)


def test_normalize_lowercases_and_strips():
    assert normalize_title("The Matrix") == "matrix"
    assert normalize_title("La Vita è Bella") == "vita e bella"


def test_normalize_drops_articles_in_languages():
    assert normalize_title("The Avengers") == "avengers"
    assert normalize_title("Le Pacte Des Loups") == "pacte des loups"
    assert normalize_title("Il Padrino") == "padrino"


def test_normalize_drops_year_in_parentheses():
    assert normalize_title("Dune (2021)") == "dune"


def test_similarity_identical_is_100():
    assert title_similarity("foo", "foo") == 100


def test_similarity_completely_different_is_low():
    assert title_similarity("Avengers", "Nightmare Before Christmas") < 50


def test_similarity_punctuation_insensitive():
    assert title_similarity("Spider-Man: No Way Home", "Spider Man No Way Home") >= 90


def test_best_match_picks_highest_score_above_threshold():
    candidates = [
        type("C", (), {"title": "The Matrix Reloaded", "year": 2003}),
        type("C", (), {"title": "The Matrix", "year": 1999}),
        type("C", (), {"title": "Matrix Revolution", "year": 2003}),
    ]
    pick = best_match(candidates, target_title="The Matrix", target_year=1999)
    assert pick is not None
    assert pick.year == 1999


def test_best_match_returns_none_when_below_threshold():
    candidates = [type("C", (), {"title": "Completely Different", "year": 2020})]
    pick = best_match(candidates, target_title="The Matrix", target_year=1999)
    assert pick is None


def test_best_match_year_proximity_breaks_ties():
    candidates = [
        type("C", (), {"title": "Star Wars", "year": 1977}),
        type("C", (), {"title": "Star Wars", "year": 2015}),
    ]
    pick = best_match(candidates, target_title="Star Wars", target_year=1977)
    assert pick.year == 1977
```

- [ ] **Step 2: Run, expect FAIL**

```bash
venv/bin/pytest tests/catalog/test_match.py -v
```

- [ ] **Step 3: Implement `streamload/catalog/match.py`**

```python
"""Title normalization + fuzzy matching using rapidfuzz.

Normalization strips:
- leading articles ("the", "il", "la", "le", "lo", "les", "el")
- year in parentheses
- diacritics
- punctuation
- excess whitespace

Match score combines title fuzzy similarity (rapidfuzz token_set_ratio)
with optional year proximity (±1 year accepted, larger penalty beyond).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional, Protocol, TypeVar

from rapidfuzz import fuzz

_LEADING_ARTICLES = {
    "the", "a", "an",
    "il", "la", "le", "lo", "li", "gli", "i",
    "el", "los", "las",
    "der", "die", "das",
    "le", "les", "la", "l'",
    "de",
}

_YEAR_RE = re.compile(r"\(\d{4}\)")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_title(title: str) -> str:
    """Lowercase, strip articles, year, diacritics, punctuation."""
    s = title.strip().lower()
    s = _YEAR_RE.sub("", s)
    # Strip diacritics (è -> e)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # Strip punctuation
    s = _PUNCT_RE.sub(" ", s)
    # Drop leading article if any
    parts = s.split()
    while parts and parts[0] in _LEADING_ARTICLES:
        parts = parts[1:]
    return " ".join(parts).strip()


def title_similarity(a: str, b: str) -> int:
    """0-100 similarity score using token_set_ratio (order-insensitive)."""
    return int(fuzz.token_set_ratio(normalize_title(a), normalize_title(b)))


class _Candidate(Protocol):
    title: str
    year: Optional[int]


T = TypeVar("T", bound=_Candidate)


def best_match(
    candidates: Iterable[T],
    *,
    target_title: str,
    target_year: Optional[int] = None,
    min_score: int = 80,
) -> Optional[T]:
    """Pick the candidate with the highest combined score.

    The score is title similarity (0-100) minus a penalty for year drift:
    - same year: 0
    - ±1 year: -5
    - ±2 years: -15
    - more: -30 (still possible to win if title is uniquely strong)

    Returns ``None`` when no candidate scores >= ``min_score`` (after penalty).
    """
    best: tuple[Optional[T], int] = (None, -1)
    for c in candidates:
        sim = title_similarity(target_title, c.title)
        penalty = 0
        if target_year is not None and c.year is not None:
            d = abs(target_year - c.year)
            if d == 1:
                penalty = 5
            elif d == 2:
                penalty = 15
            elif d > 2:
                penalty = 30
        score = sim - penalty
        if score > best[1]:
            best = (c, score)
    if best[0] is None or best[1] < min_score:
        return None
    return best[0]
```

- [ ] **Step 4: Run, expect PASS**

```bash
venv/bin/pytest tests/catalog/test_match.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/catalog/match.py tests/catalog/test_match.py
git commit -m "feat(catalog): title normalization + fuzzy match (rapidfuzz)"
```

---

## Task 4: Async wrapper for v1 service `search()`

**Files:**
- Modify: `streamload/services/base.py`
- Create: `tests/services/test_async_search.py`

- [ ] **Step 1: Failing test**

`tests/services/test_async_search.py`:
```python
"""Default async wrapper for v1 sync search()."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from streamload.models.media import MediaEntry, MediaType, ServiceCategory
from streamload.services.base import ServiceBase


class _FakeService(ServiceBase):
    name = "Fake"
    short_name = "fake"
    domains = ["example.tld"]
    category = ServiceCategory.FILM_SERIE
    language = "it"

    def search(self, query):
        return [MediaEntry(id="1", title=query, type=MediaType.FILM, url="https://x", service="fake")]

    def get_seasons(self, e): return []
    def get_episodes(self, s): return []
    def get_streams(self, i): raise NotImplementedError


@pytest.mark.asyncio
async def test_search_async_returns_same_as_sync():
    s = _FakeService(http_client=MagicMock())
    out = await s.search_async("hello")
    assert len(out) == 1
    assert out[0].title == "hello"
```

- [ ] **Step 2: Run, expect FAIL**

```bash
venv/bin/pytest tests/services/test_async_search.py -v
```
Expected: FAIL — `search_async` missing.

- [ ] **Step 3: Add to `streamload/services/base.py`**

Insert in `ServiceBase` class:

```python
import asyncio


async def search_async(self, query: str) -> list[MediaEntry]:
    """Async wrapper for the sync ``search()`` method.

    Default implementation runs the sync method on a thread. Services
    can override with a true async implementation when convenient.
    """
    return await asyncio.to_thread(self.search, query)
```

(Add `import asyncio` at the top if not already present.)

- [ ] **Step 4: Run, expect PASS**

```bash
venv/bin/pytest tests/services/test_async_search.py -v
```

- [ ] **Step 5: Commit**

```bash
git add streamload/services/base.py tests/services/test_async_search.py
git commit -m "feat(services): default async wrapper for v1 sync search()"
```

---

## Task 5: Collection definitions

**Files:**
- Create: `streamload/catalog/collections.py`
- Create: `tests/catalog/test_collections.py`

- [ ] **Step 1: Failing test**

`tests/catalog/test_collections.py`:
```python
from streamload.catalog.collections import (
    COLLECTION_DEFS,
    CollectionDef,
    get_collection_def,
)


def test_all_definitions_have_unique_ids():
    ids = [d.id for d in COLLECTION_DEFS]
    assert len(ids) == len(set(ids))


def test_definitions_have_required_fields():
    for d in COLLECTION_DEFS:
        assert d.id
        assert d.title
        assert d.fetch
        assert d.refresh_ttl_hours > 0


def test_get_collection_def_lookup():
    d = get_collection_def("trending-day")
    assert d is not None
    assert d.id == "trending-day"


def test_get_collection_def_unknown_returns_none():
    assert get_collection_def("nonexistent") is None
```

- [ ] **Step 2: Run, expect FAIL**

```bash
venv/bin/pytest tests/catalog/test_collections.py -v
```

- [ ] **Step 3: Implement `streamload/catalog/collections.py`**

```python
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
```

- [ ] **Step 4: Run, expect PASS**

```bash
venv/bin/pytest tests/catalog/test_collections.py -v
```

- [ ] **Step 5: Commit**

```bash
git add streamload/catalog/collections.py tests/catalog/test_collections.py
git commit -m "feat(catalog): TMDB collection definitions for home rows"
```

---

## Task 6: Source ranker

**Files:**
- Create: `streamload/catalog/ranker.py`
- Create: `tests/catalog/test_ranker.py`

- [ ] **Step 1: Failing test**

`tests/catalog/test_ranker.py`:
```python
from datetime import UTC, datetime, timedelta

from streamload.catalog.ranker import (
    DEFAULT_WEIGHTS,
    RankedSource,
    SourceMetrics,
    rank_sources,
)


def _ms(quality=720, latency=1000, success=10, fail=0, audio=("ita",), subs=("ita", "eng")):
    return SourceMetrics(
        service_short_name="x",
        service_url="https://x",
        service_media_id="1",
        quality_max_height=quality,
        latency_ttfb_ms=latency,
        success_count=success,
        failure_count=fail,
        audio_languages=list(audio),
        subtitle_languages=list(subs),
        last_verified_at=datetime.now(UTC),
    )


def test_higher_quality_wins_at_equal_other():
    sources = [
        _ms(quality=480), _ms(quality=720), _ms(quality=1080),
    ]
    ranked = rank_sources(sources)
    assert ranked[0].metrics.quality_max_height == 1080
    assert ranked[2].metrics.quality_max_height == 480


def test_labels_assigned_in_rank_order():
    sources = [_ms(quality=480), _ms(quality=1080)]
    ranked = rank_sources(sources)
    assert ranked[0].label == "Server 1"
    assert ranked[1].label == "Server 2"


def test_lower_latency_breaks_quality_tie():
    sources = [
        _ms(quality=720, latency=2000),
        _ms(quality=720, latency=400),
    ]
    ranked = rank_sources(sources)
    assert ranked[0].metrics.latency_ttfb_ms == 400


def test_unreliable_source_ranked_lower():
    a = _ms(quality=720, success=10, fail=0)
    b = _ms(quality=720, success=2, fail=8)
    ranked = rank_sources([b, a])
    assert ranked[0].metrics is a


def test_audio_match_boost_when_user_pref_present():
    # User wants 'ita' audio
    a = _ms(quality=720, audio=("eng",))
    b = _ms(quality=720, audio=("ita", "eng"))
    ranked = rank_sources([a, b], user_audio_pref="ita")
    assert ranked[0].metrics is b


def test_subs_match_boost_when_user_pref_present():
    a = _ms(quality=720, subs=("eng",))
    b = _ms(quality=720, subs=("ita", "eng"))
    ranked = rank_sources([a, b], user_subs_pref="ita")
    assert ranked[0].metrics is b


def test_score_is_normalized_0_to_100():
    sources = [_ms(quality=1080)]
    ranked = rank_sources(sources)
    assert 0 <= ranked[0].score <= 100


def test_empty_input_returns_empty_list():
    assert rank_sources([]) == []
```

- [ ] **Step 2: Run, expect FAIL**

```bash
venv/bin/pytest tests/catalog/test_ranker.py -v
```

- [ ] **Step 3: Implement `streamload/catalog/ranker.py`**

```python
"""Source ranker.

Combines normalized 0-100 sub-scores into a final score per source. The
top-ranked source is "Server 1", next "Server 2", etc.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# Default weights, sum to 1.0.
DEFAULT_WEIGHTS = {
    "quality": 0.40,
    "latency": 0.20,
    "reliability": 0.20,
    "audio_match": 0.10,
    "subs_match": 0.10,
}


@dataclass
class SourceMetrics:
    service_short_name: str
    service_url: str
    service_media_id: str
    quality_max_height: Optional[int]
    latency_ttfb_ms: Optional[int]
    success_count: int
    failure_count: int
    audio_languages: list[str]
    subtitle_languages: list[str]
    last_verified_at: datetime


@dataclass
class RankedSource:
    label: str
    metrics: SourceMetrics
    score: float


def _quality_score(height: Optional[int]) -> float:
    if height is None:
        return 30.0
    if height >= 2160:
        return 100.0
    if height >= 1080:
        return 100.0
    if height >= 720:
        return 70.0
    if height >= 480:
        return 40.0
    return 20.0


def _latency_score(ms: Optional[int]) -> float:
    if ms is None:
        return 50.0
    if ms <= 500:
        return 100.0
    if ms <= 1500:
        return 70.0
    if ms <= 3000:
        return 40.0
    return 20.0


def _reliability_score(success: int, failure: int) -> float:
    if success + failure == 0:
        return 60.0  # neutral for unverified
    rate = success / (success + failure)
    return rate * 100.0


def _audio_match_score(langs: list[str], pref: Optional[str]) -> float:
    if pref is None:
        return 50.0
    return 100.0 if pref in langs else 50.0


def _subs_match_score(langs: list[str], pref: Optional[str]) -> float:
    if pref is None:
        return 50.0
    return 100.0 if pref in langs else 50.0


def rank_sources(
    sources: list[SourceMetrics],
    *,
    user_audio_pref: Optional[str] = "ita",
    user_subs_pref: Optional[str] = "ita",
    weights: Optional[dict[str, float]] = None,
) -> list[RankedSource]:
    if not sources:
        return []
    w = weights or DEFAULT_WEIGHTS
    ranked: list[tuple[float, SourceMetrics]] = []
    for s in sources:
        score = (
            w["quality"] * _quality_score(s.quality_max_height)
            + w["latency"] * _latency_score(s.latency_ttfb_ms)
            + w["reliability"] * _reliability_score(s.success_count, s.failure_count)
            + w["audio_match"] * _audio_match_score(s.audio_languages, user_audio_pref)
            + w["subs_match"] * _subs_match_score(s.subtitle_languages, user_subs_pref)
        )
        ranked.append((score, s))
    ranked.sort(key=lambda t: t[0], reverse=True)
    return [
        RankedSource(label=f"Server {i+1}", metrics=m, score=round(s, 2))
        for i, (s, m) in enumerate(ranked)
    ]
```

- [ ] **Step 4: Run, expect PASS**

```bash
venv/bin/pytest tests/catalog/test_ranker.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/catalog/ranker.py tests/catalog/test_ranker.py
git commit -m "feat(catalog): source ranker with weighted scoring"
```

---

## Task 7: Catalog ingestion orchestrator

**Files:**
- Create: `streamload/catalog/ingest.py`
- Create: `tests/catalog/test_ingest.py`

- [ ] **Step 1: Failing test**

`tests/catalog/test_ingest.py`:
```python
"""Catalog ingestion orchestrator.

Verifies that for a TMDB collection result, services are queried in
parallel and matching results are persisted as catalog_sources.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from streamload.catalog.ingest import ingest_collection
from streamload.catalog.tmdb import TmdbItem
from streamload.db import create_engine, create_session_factory
from streamload.db.models import CatalogItem, CatalogSource, Collection, CollectionItem
from streamload.models.media import MediaEntry, MediaType


@pytest_asyncio.fixture
async def db_session():
    url = os.environ.get(
        "DATABASE_URL_TEST",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test",
    )
    engine = create_engine(url)
    factory = create_session_factory(engine)
    async with factory() as s:
        for tbl in ("collection_items", "catalog_sources", "tv_episodes",
                    "catalog_items", "collections"):
            await s.execute(text(f"TRUNCATE TABLE {tbl} CASCADE"))
        await s.commit()
        yield s
    await engine.dispose()


def _fake_service(name: str, short: str, results: list[MediaEntry]):
    svc = MagicMock()
    svc.name = name
    svc.short_name = short
    svc.search_async = AsyncMock(return_value=results)
    return svc


@pytest.mark.asyncio
async def test_ingest_persists_collection_items(db_session):
    items = [
        TmdbItem(tmdb_id=100, media_type="movie", title="Movie A", year=2024),
        TmdbItem(tmdb_id=200, media_type="movie", title="Movie B", year=2023),
    ]
    services = [
        _fake_service("SC", "sc", [
            MediaEntry(id="sc1", title="Movie A", type=MediaType.FILM, url="https://sc/a", service="sc", year=2024),
        ]),
        _fake_service("AU", "au", []),
    ]
    await ingest_collection(
        db_session,
        collection_id="trending-day",
        collection_title="Trending oggi",
        media_type=None,
        sort_order=10,
        refresh_ttl_hours=6,
        items=items,
        services=services,
    )
    items_db = (await db_session.execute(select(CatalogItem))).scalars().all()
    assert len(items_db) == 2

    sources = (await db_session.execute(select(CatalogSource))).scalars().all()
    # Only Movie A was matched by SC
    assert len(sources) == 1
    assert sources[0].tmdb_id == 100
    assert sources[0].service_short_name == "sc"

    coll_items = (await db_session.execute(select(CollectionItem))).scalars().all()
    assert {ci.tmdb_id for ci in coll_items} == {100, 200}


@pytest.mark.asyncio
async def test_ingest_creates_collection_row(db_session):
    items = [TmdbItem(tmdb_id=1, media_type="movie", title="X", year=2024)]
    await ingest_collection(
        db_session, collection_id="c1", collection_title="C1",
        media_type="movie", sort_order=1, refresh_ttl_hours=24,
        items=items, services=[],
    )
    coll = (await db_session.execute(select(Collection).where(Collection.id == "c1"))).scalar_one()
    assert coll.title == "C1"
    assert coll.last_refreshed_at is not None


@pytest.mark.asyncio
async def test_ingest_replaces_collection_items_on_refresh(db_session):
    items_v1 = [TmdbItem(tmdb_id=1, media_type="movie", title="X", year=2024)]
    items_v2 = [TmdbItem(tmdb_id=2, media_type="movie", title="Y", year=2024)]
    for items in (items_v1, items_v2):
        await ingest_collection(
            db_session, collection_id="c1", collection_title="C1",
            media_type="movie", sort_order=1, refresh_ttl_hours=24,
            items=items, services=[],
        )
    coll_items = (await db_session.execute(select(CollectionItem))).scalars().all()
    assert {ci.tmdb_id for ci in coll_items} == {2}
```

- [ ] **Step 2: Run, expect FAIL**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/catalog/test_ingest.py -v
```

- [ ] **Step 3: Implement `streamload/catalog/ingest.py`**

```python
"""Orchestrator: TMDB items -> reverse lookup -> persist catalog state."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db.models import (
    CatalogItem,
    CatalogSource,
    Collection,
    CollectionItem,
)
from streamload.utils.logger import get_logger

from .match import best_match
from .tmdb import TmdbItem

log = get_logger(__name__)

REVERSE_LOOKUP_CONCURRENCY = 8


async def _upsert_catalog_item(db: AsyncSession, item: TmdbItem) -> None:
    stmt = insert(CatalogItem).values(
        tmdb_id=item.tmdb_id,
        media_type=item.media_type,
        title=item.title,
        original_title=item.original_title,
        year=item.year,
        poster_url=item.poster_url,
        backdrop_url=item.backdrop_url,
        overview=item.overview,
        rating=item.rating,
        runtime_minutes=item.runtime_minutes,
        seasons_count=item.seasons_count,
        genres=item.genres,
        metadata_fetched_at=datetime.now(UTC),
    ).on_conflict_do_update(
        index_elements=["tmdb_id"],
        set_={
            "title": item.title,
            "original_title": item.original_title,
            "year": item.year,
            "poster_url": item.poster_url,
            "backdrop_url": item.backdrop_url,
            "overview": item.overview,
            "rating": item.rating,
            "runtime_minutes": item.runtime_minutes,
            "seasons_count": item.seasons_count,
            "genres": item.genres,
            "metadata_fetched_at": datetime.now(UTC),
        },
    )
    await db.execute(stmt)


async def _resolve_sources_for_item(
    db: AsyncSession,
    item: TmdbItem,
    services: list[Any],
    sem: asyncio.Semaphore,
) -> int:
    """Search each service for *item.title*. Persist matched sources. Returns count matched."""
    matched = 0
    for svc in services:
        async with sem:
            try:
                results = await svc.search_async(item.title)
            except Exception:
                log.warning("Service %s search failed for %r", svc.short_name, item.title, exc_info=True)
                continue
        match = best_match(results, target_title=item.title, target_year=item.year)
        if match is None:
            continue
        # Upsert catalog_sources row
        stmt = insert(CatalogSource).values(
            tmdb_id=item.tmdb_id,
            service_short_name=svc.short_name,
            service_url=match.url,
            service_media_id=str(match.id),
            quality_max_height=None,
            languages_audio=[],
            languages_subs=[],
            last_verified_at=datetime.now(UTC),
        ).on_conflict_do_update(
            index_elements=["tmdb_id", "service_short_name"],
            set_={
                "service_url": match.url,
                "service_media_id": str(match.id),
                "last_verified_at": datetime.now(UTC),
            },
        )
        await db.execute(stmt)
        matched += 1
    return matched


async def ingest_collection(
    db: AsyncSession,
    *,
    collection_id: str,
    collection_title: str,
    media_type: Optional[str],
    sort_order: int,
    refresh_ttl_hours: int,
    items: list[TmdbItem],
    services: list[Any],
) -> None:
    """Full ingest cycle for a collection.

    1. Upsert collection row
    2. Upsert each catalog_item
    3. For each item: parallel reverse-lookup on services, persist sources
    4. Replace collection_items membership with the new ordering
    """
    log.info("Ingesting collection %s (%d items)", collection_id, len(items))

    # 1. Collection row
    coll_stmt = insert(Collection).values(
        id=collection_id, title=collection_title, media_type=media_type,
        sort_order=sort_order, refresh_ttl_hours=refresh_ttl_hours,
        last_refreshed_at=datetime.now(UTC),
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={
            "title": collection_title, "media_type": media_type,
            "sort_order": sort_order, "refresh_ttl_hours": refresh_ttl_hours,
            "last_refreshed_at": datetime.now(UTC),
        },
    )
    await db.execute(coll_stmt)

    # 2. Catalog items
    for it in items:
        await _upsert_catalog_item(db, it)

    # 3. Reverse-lookup sources in parallel
    sem = asyncio.Semaphore(REVERSE_LOOKUP_CONCURRENCY)
    await asyncio.gather(*[
        _resolve_sources_for_item(db, it, services, sem) for it in items
    ])

    # 4. Replace collection_items
    await db.execute(
        delete(CollectionItem).where(CollectionItem.collection_id == collection_id)
    )
    for pos, it in enumerate(items):
        db.add(CollectionItem(
            collection_id=collection_id, tmdb_id=it.tmdb_id, position=pos,
        ))

    await db.commit()
    log.info("Ingest complete for %s", collection_id)
```

- [ ] **Step 4: Run, expect PASS**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/catalog/test_ingest.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/catalog/ingest.py tests/catalog/test_ingest.py
git commit -m "feat(catalog): ingestion orchestrator with parallel reverse lookup"
```

---

## Task 8: Catalog service facade

**Files:**
- Create: `streamload/catalog/service.py`
- Create: `tests/catalog/test_service.py`

- [ ] **Step 1: Failing test**

`tests/catalog/test_service.py`:
```python
import os
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text

from streamload.catalog.service import CatalogService
from streamload.db import create_engine, create_session_factory
from streamload.db.models import (
    CatalogItem, CatalogSource, Collection, CollectionItem,
)


@pytest_asyncio.fixture
async def db_session():
    url = os.environ.get(
        "DATABASE_URL_TEST",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test",
    )
    engine = create_engine(url)
    factory = create_session_factory(engine)
    async with factory() as s:
        for tbl in ("collection_items", "catalog_sources", "tv_episodes",
                    "catalog_items", "collections"):
            await s.execute(text(f"TRUNCATE TABLE {tbl} CASCADE"))
        await s.commit()
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded(db_session):
    db_session.add_all([
        Collection(id="c1", title="C1", sort_order=1, refresh_ttl_hours=24,
                   last_refreshed_at=datetime.now(UTC)),
        CatalogItem(tmdb_id=1, media_type="movie", title="A", year=2024),
        CatalogItem(tmdb_id=2, media_type="movie", title="B", year=2024),
        CatalogSource(tmdb_id=1, service_short_name="sc", service_url="https://sc/1", service_media_id="1"),
        CatalogSource(tmdb_id=1, service_short_name="rp", service_url="https://rp/1", service_media_id="1"),
        CollectionItem(collection_id="c1", tmdb_id=1, position=0),
        CollectionItem(collection_id="c1", tmdb_id=2, position=1),
    ])
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_item_returns_with_sources(db_session, seeded):
    s = CatalogService(db_session)
    item = await s.get_item(1)
    assert item is not None
    assert item.title == "A"
    assert len(item.sources) == 2


@pytest.mark.asyncio
async def test_get_item_unknown_returns_none(db_session, seeded):
    s = CatalogService(db_session)
    assert await s.get_item(9999) is None


@pytest.mark.asyncio
async def test_get_collection_returns_items_in_order(db_session, seeded):
    s = CatalogService(db_session)
    coll = await s.get_collection("c1")
    assert coll is not None
    ids = [i.tmdb_id for i in coll.items]
    assert ids == [1, 2]


@pytest.mark.asyncio
async def test_list_collections_sorted(db_session):
    db_session.add_all([
        Collection(id="b", title="B", sort_order=20, refresh_ttl_hours=24,
                   last_refreshed_at=datetime.now(UTC)),
        Collection(id="a", title="A", sort_order=10, refresh_ttl_hours=24,
                   last_refreshed_at=datetime.now(UTC)),
    ])
    await db_session.commit()
    s = CatalogService(db_session)
    out = await s.list_collections()
    assert [c.id for c in out] == ["a", "b"]
```

- [ ] **Step 2: Run, expect FAIL**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/catalog/test_service.py -v
```

- [ ] **Step 3: Implement `streamload/catalog/service.py`**

```python
"""Catalog facade — read-side API for routes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from streamload.db.models import (
    CatalogItem,
    CatalogSource,
    Collection,
    CollectionItem,
)


@dataclass
class CollectionWithItems:
    id: str
    title: str
    sort_order: int
    items: list[CatalogItem]


class CatalogService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_item(self, tmdb_id: int) -> Optional[CatalogItem]:
        stmt = (
            select(CatalogItem)
            .options(selectinload(CatalogItem.sources))
            .where(CatalogItem.tmdb_id == tmdb_id)
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_collections(self) -> list[Collection]:
        stmt = select(Collection).order_by(Collection.sort_order)
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_collection(self, collection_id: str) -> Optional[CollectionWithItems]:
        coll = (await self._db.execute(
            select(Collection).where(Collection.id == collection_id)
        )).scalar_one_or_none()
        if coll is None:
            return None
        items_stmt = (
            select(CatalogItem)
            .join(CollectionItem, CollectionItem.tmdb_id == CatalogItem.tmdb_id)
            .where(CollectionItem.collection_id == collection_id)
            .order_by(CollectionItem.position)
        )
        items = list((await self._db.execute(items_stmt)).scalars().all())
        return CollectionWithItems(
            id=coll.id, title=coll.title, sort_order=coll.sort_order, items=items,
        )
```

- [ ] **Step 4: Run, expect PASS**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/catalog/test_service.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/catalog/service.py tests/catalog/test_service.py
git commit -m "feat(catalog): read-side service facade"
```

---

## Task 9: Catalog API routes

**Files:**
- Create: `streamload/api/routes/catalog.py`
- Create: `streamload/api/routes/collections.py`
- Modify: `streamload/api/app.py`
- Create: `tests/api/test_catalog.py`
- Create: `tests/api/test_collections.py`

- [ ] **Step 1: Failing tests**

`tests/api/test_catalog.py`:
```python
import os
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem, CatalogSource


@pytest.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "u", "email": "u@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_get_catalog_item(api_client, authed):
    async for db in gs():
        db.add(CatalogItem(tmdb_id=42, media_type="movie", title="Foo", year=2024))
        db.add(CatalogSource(
            tmdb_id=42, service_short_name="sc", service_url="https://sc/42",
            service_media_id="42", quality_max_height=1080,
        ))
        await db.commit()
        break
    r = await api_client.get("/api/catalog/42")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Foo"
    assert len(body["sources"]) == 1
    assert body["sources"][0]["label"] == "Server 1"
    assert body["sources"][0]["score"] > 0


@pytest.mark.asyncio
async def test_get_catalog_item_404(api_client, authed):
    r = await api_client.get("/api/catalog/9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_catalog_requires_auth(api_client):
    r = await api_client.get("/api/catalog/42")
    assert r.status_code == 401
```

`tests/api/test_collections.py`:
```python
from datetime import UTC, datetime

import httpx
import pytest

from streamload.db import get_session as gs
from streamload.db.models import (
    CatalogItem, Collection, CollectionItem,
)


@pytest.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "u", "email": "u@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_list_collections(api_client, authed):
    async for db in gs():
        db.add_all([
            Collection(id="a", title="A", sort_order=10, refresh_ttl_hours=24,
                       last_refreshed_at=datetime.now(UTC)),
            Collection(id="b", title="B", sort_order=20, refresh_ttl_hours=24,
                       last_refreshed_at=datetime.now(UTC)),
        ])
        await db.commit()
        break
    r = await api_client.get("/api/collections")
    assert r.status_code == 200
    body = r.json()
    assert [c["id"] for c in body] == ["a", "b"]


@pytest.mark.asyncio
async def test_get_collection_items(api_client, authed):
    async for db in gs():
        db.add_all([
            Collection(id="a", title="A", sort_order=10, refresh_ttl_hours=24,
                       last_refreshed_at=datetime.now(UTC)),
            CatalogItem(tmdb_id=1, media_type="movie", title="X", year=2024),
            CatalogItem(tmdb_id=2, media_type="movie", title="Y", year=2024),
            CollectionItem(collection_id="a", tmdb_id=2, position=0),
            CollectionItem(collection_id="a", tmdb_id=1, position=1),
        ])
        await db.commit()
        break
    r = await api_client.get("/api/collections/a")
    assert r.status_code == 200
    body = r.json()
    assert [i["tmdb_id"] for i in body["items"]] == [2, 1]


@pytest.mark.asyncio
async def test_get_unknown_collection_404(api_client, authed):
    r = await api_client.get("/api/collections/nope")
    assert r.status_code == 404
```

- [ ] **Step 2: Run, expect FAIL**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_catalog.py tests/api/test_collections.py -v
```

- [ ] **Step 3: Implement `streamload/api/routes/catalog.py`**

```python
"""Catalog detail endpoint."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from streamload.api.deps import CurrentUser, SessionDep
from streamload.catalog.ranker import SourceMetrics, rank_sources
from streamload.catalog.service import CatalogService

router = APIRouter(prefix="/catalog", tags=["catalog"])


class SourceResponse(BaseModel):
    label: str
    score: float


class CatalogItemResponse(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    original_title: str | None
    year: int | None
    poster_url: str | None
    backdrop_url: str | None
    overview: str | None
    rating: float | None
    runtime_minutes: int | None
    seasons_count: int | None
    genres: list[str]
    sources: list[SourceResponse]


@router.get("/{tmdb_id}", response_model=CatalogItemResponse)
async def get_item(tmdb_id: int, db: SessionDep, user: CurrentUser) -> CatalogItemResponse:
    svc = CatalogService(db)
    item = await svc.get_item(tmdb_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "title not found in catalog")
    metrics = [
        SourceMetrics(
            service_short_name=s.service_short_name,
            service_url=s.service_url,
            service_media_id=s.service_media_id,
            quality_max_height=s.quality_max_height,
            latency_ttfb_ms=None,
            success_count=s.success_count,
            failure_count=s.failure_count,
            audio_languages=s.languages_audio,
            subtitle_languages=s.languages_subs,
            last_verified_at=s.last_verified_at,
        ) for s in item.sources
    ]
    ranked = rank_sources(metrics, user_audio_pref="ita", user_subs_pref="ita")
    return CatalogItemResponse(
        tmdb_id=item.tmdb_id,
        media_type=item.media_type,
        title=item.title,
        original_title=item.original_title,
        year=item.year,
        poster_url=item.poster_url,
        backdrop_url=item.backdrop_url,
        overview=item.overview,
        rating=float(item.rating) if item.rating is not None else None,
        runtime_minutes=item.runtime_minutes,
        seasons_count=item.seasons_count,
        genres=item.genres,
        sources=[SourceResponse(label=r.label, score=r.score) for r in ranked],
    )
```

- [ ] **Step 4: Implement `streamload/api/routes/collections.py`**

```python
"""Collection list + detail endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from streamload.api.deps import CurrentUser, SessionDep
from streamload.catalog.service import CatalogService

router = APIRouter(prefix="/collections", tags=["collections"])


class CollectionSummary(BaseModel):
    id: str
    title: str
    sort_order: int
    media_type: str | None


class CatalogItemSummary(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    year: int | None
    poster_url: str | None


class CollectionDetail(BaseModel):
    id: str
    title: str
    sort_order: int
    items: list[CatalogItemSummary]


@router.get("", response_model=list[CollectionSummary])
async def list_collections(db: SessionDep, user: CurrentUser) -> list[CollectionSummary]:
    svc = CatalogService(db)
    out = await svc.list_collections()
    return [
        CollectionSummary(id=c.id, title=c.title, sort_order=c.sort_order, media_type=c.media_type)
        for c in out
    ]


@router.get("/{collection_id}", response_model=CollectionDetail)
async def get_collection(collection_id: str, db: SessionDep, user: CurrentUser) -> CollectionDetail:
    svc = CatalogService(db)
    coll = await svc.get_collection(collection_id)
    if coll is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "collection not found")
    return CollectionDetail(
        id=coll.id,
        title=coll.title,
        sort_order=coll.sort_order,
        items=[
            CatalogItemSummary(
                tmdb_id=i.tmdb_id, media_type=i.media_type,
                title=i.title, year=i.year, poster_url=i.poster_url,
            ) for i in coll.items
        ],
    )
```

- [ ] **Step 5: Wire routers in `app.py`**

```python
from .routes import auth, catalog, collections, email, health, me, passkey
# in create_app:
app.include_router(catalog.router, prefix="/api")
app.include_router(collections.router, prefix="/api")
```

- [ ] **Step 6: Run, expect PASS**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_catalog.py tests/api/test_collections.py -v
```
Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add streamload/api/routes/catalog.py streamload/api/routes/collections.py streamload/api/app.py tests/api/test_catalog.py tests/api/test_collections.py
git commit -m "feat(api): catalog detail + collections list/detail endpoints"
```

---

## Task 10: Search endpoint

**Files:**
- Create: `streamload/api/routes/search.py`
- Modify: `streamload/api/app.py`
- Create: `tests/api/test_search.py`

- [ ] **Step 1: Failing test**

`tests/api/test_search.py`:
```python
"""Live search via TMDB."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from streamload.catalog.tmdb import TmdbItem


@pytest.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "u", "email": "u@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_search_returns_tmdb_results(api_client, authed):
    fake_results = [
        TmdbItem(tmdb_id=1, media_type="movie", title="Foo", year=2024,
                 poster_url="https://image.tmdb.org/t/p/w500/x.jpg"),
        TmdbItem(tmdb_id=2, media_type="tv", title="Bar", year=2023,
                 poster_url="https://image.tmdb.org/t/p/w500/y.jpg"),
    ]
    with patch("streamload.api.routes.search._build_tmdb_client") as mk:
        client = mk.return_value
        client.search_multi = AsyncMock(return_value=fake_results)
        r = await api_client.get("/api/search", params={"q": "foo"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 2


@pytest.mark.asyncio
async def test_search_empty_query_returns_400(api_client, authed):
    r = await api_client.get("/api/search", params={"q": ""})
    assert r.status_code == 422
```

- [ ] **Step 2: Run, expect FAIL**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_search.py -v
```

- [ ] **Step 3: Implement `streamload/api/routes/search.py`**

```python
"""Live search endpoint — queries TMDB and returns typed results."""
from __future__ import annotations

import os

from fastapi import APIRouter, Query
from pydantic import BaseModel

from streamload.api.deps import CurrentUser
from streamload.catalog.tmdb import TmdbClient
from streamload.utils.http import HttpClient

router = APIRouter(prefix="/search", tags=["search"])


class SearchResult(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    year: int | None
    poster_url: str | None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


def _build_tmdb_client() -> TmdbClient:
    api_key = os.environ.get("TMDB_API_KEY", "")
    # For now, wrap the v1 HttpClient — async-friendly via .get_async() (Plan 1+)
    # For Plan 2, we use httpx.AsyncClient directly to keep it simple.
    import httpx
    http = httpx.AsyncClient(timeout=15)
    return TmdbClient(api_key=api_key, http=http)


@router.get("", response_model=SearchResponse)
async def search(
    user: CurrentUser,
    q: str = Query(min_length=1, max_length=100),
) -> SearchResponse:
    client = _build_tmdb_client()
    items = await client.search_multi(q)
    return SearchResponse(
        query=q,
        results=[
            SearchResult(
                tmdb_id=i.tmdb_id, media_type=i.media_type,
                title=i.title, year=i.year, poster_url=i.poster_url,
            ) for i in items
        ],
    )
```

- [ ] **Step 4: Wire router**

`streamload/api/app.py`:
```python
from .routes import auth, catalog, collections, email, health, me, passkey, search
# in create_app:
app.include_router(search.router, prefix="/api")
```

- [ ] **Step 5: Run, expect PASS**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_search.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add streamload/api/routes/search.py streamload/api/app.py tests/api/test_search.py
git commit -m "feat(api): live search endpoint via TMDB"
```

---

## Task 11: Background catalog refresh worker

**Files:**
- Create: `streamload/catalog/worker.py`
- Create: `tests/catalog/test_worker.py`

- [ ] **Step 1: Failing test**

`tests/catalog/test_worker.py`:
```python
"""Catalog refresh worker logic (no scheduler loop)."""
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import text

from streamload.catalog.collections import CollectionDef
from streamload.catalog.tmdb import TmdbItem
from streamload.catalog.worker import refresh_due_collections
from streamload.db import create_engine, create_session_factory
from streamload.db.models import Collection


@pytest_asyncio.fixture
async def db_session():
    url = os.environ.get(
        "DATABASE_URL_TEST",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test",
    )
    engine = create_engine(url)
    factory = create_session_factory(engine)
    async with factory() as s:
        for tbl in ("collection_items", "catalog_sources", "tv_episodes",
                    "catalog_items", "collections"):
            await s.execute(text(f"TRUNCATE TABLE {tbl} CASCADE"))
        await s.commit()
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_refresh_runs_collections_past_ttl(db_session):
    # Seed an old collection (last refreshed 2 days ago, ttl=24h -> due)
    old = datetime.now(UTC) - timedelta(hours=48)
    db_session.add(Collection(
        id="trending-day", title="X", sort_order=10,
        refresh_ttl_hours=24, last_refreshed_at=old,
    ))
    await db_session.commit()

    fake_tmdb = MagicMock()
    fake_tmdb.trending_day = AsyncMock(return_value=[
        TmdbItem(tmdb_id=1, media_type="movie", title="Y", year=2024),
    ])
    test_def = CollectionDef(
        id="trending-day", title="Trending oggi", media_type=None,
        sort_order=10, refresh_ttl_hours=24,
        fetch=lambda c: c.trending_day(),
    )
    refreshed = await refresh_due_collections(
        db_session, tmdb_client=fake_tmdb, services=[],
        collection_defs=[test_def],
    )
    assert refreshed == ["trending-day"]


@pytest.mark.asyncio
async def test_refresh_skips_recent_collections(db_session):
    # Refreshed 1h ago, ttl=24h -> NOT due
    recent = datetime.now(UTC) - timedelta(hours=1)
    db_session.add(Collection(
        id="trending-day", title="X", sort_order=10,
        refresh_ttl_hours=24, last_refreshed_at=recent,
    ))
    await db_session.commit()

    fake_tmdb = MagicMock()
    fake_tmdb.trending_day = AsyncMock(return_value=[])
    test_def = CollectionDef(
        id="trending-day", title="Trending oggi", media_type=None,
        sort_order=10, refresh_ttl_hours=24,
        fetch=lambda c: c.trending_day(),
    )
    refreshed = await refresh_due_collections(
        db_session, tmdb_client=fake_tmdb, services=[],
        collection_defs=[test_def],
    )
    assert refreshed == []
    fake_tmdb.trending_day.assert_not_called()
```

- [ ] **Step 2: Run, expect FAIL**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/catalog/test_worker.py -v
```

- [ ] **Step 3: Implement `streamload/catalog/worker.py`**

```python
"""Background catalog refresh worker.

Two entry points:

* ``refresh_due_collections()`` — pure function, easy to test, used by
  the scheduler tick and by the admin "force refresh" endpoint.
* ``main()`` — long-running async loop suitable for a separate process
  (systemd service or Docker container).
"""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db import init as db_init, shutdown as db_shutdown
from streamload.db.models import Collection
from streamload.utils.logger import get_logger

from .collections import COLLECTION_DEFS, CollectionDef
from .ingest import ingest_collection
from .tmdb import TmdbClient

log = get_logger(__name__)

POLL_INTERVAL_SECONDS = 600  # 10 minutes


async def refresh_due_collections(
    db: AsyncSession,
    *,
    tmdb_client: Any,
    services: list[Any],
    collection_defs: Optional[list[CollectionDef]] = None,
) -> list[str]:
    """Refresh collections whose last_refreshed_at is older than their TTL."""
    defs = collection_defs if collection_defs is not None else COLLECTION_DEFS
    now = datetime.now(UTC)
    refreshed: list[str] = []
    for d in defs:
        existing = (await db.execute(
            select(Collection).where(Collection.id == d.id)
        )).scalar_one_or_none()
        if existing is not None and existing.last_refreshed_at is not None:
            age = now - existing.last_refreshed_at
            if age < timedelta(hours=d.refresh_ttl_hours):
                log.debug("Collection %s is fresh (age=%s)", d.id, age)
                continue
        log.info("Refreshing collection %s", d.id)
        items = await d.fetch(tmdb_client)
        await ingest_collection(
            db, collection_id=d.id, collection_title=d.title,
            media_type=d.media_type, sort_order=d.sort_order,
            refresh_ttl_hours=d.refresh_ttl_hours,
            items=items, services=services,
        )
        refreshed.append(d.id)
    return refreshed


def _load_services() -> list[Any]:
    """Load all v1 service plugins."""
    from streamload.services import ServiceRegistry, load_services
    from streamload.utils.http import HttpClient
    load_services()
    http = HttpClient()
    return [cls(http) for cls in ServiceRegistry.get_all()]


async def main() -> None:
    """Long-running refresh loop. Used as a separate process."""
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload",
    )
    api_key = os.environ.get("TMDB_API_KEY", "")
    db_init(db_url)
    services = _load_services()
    try:
        while True:
            try:
                from streamload.db.session import _session_factory
                async with _session_factory() as session:
                    async with httpx.AsyncClient(timeout=15) as http:
                        tmdb = TmdbClient(api_key=api_key, http=http)
                        refreshed = await refresh_due_collections(
                            session, tmdb_client=tmdb, services=services,
                        )
                        if refreshed:
                            log.info("Refreshed: %s", ", ".join(refreshed))
            except Exception:
                log.error("Refresh tick failed", exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    finally:
        await db_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run, expect PASS**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/catalog/test_worker.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/catalog/worker.py tests/catalog/test_worker.py
git commit -m "feat(catalog): background refresh worker"
```

---

## Task 12: Admin refresh endpoint + version bump

**Files:**
- Modify: `streamload/api/routes/catalog.py`
- Modify: `streamload/version.py`
- Create: `tests/api/test_admin_refresh.py`

- [ ] **Step 1: Failing test**

`tests/api/test_admin_refresh.py`:
```python
import httpx
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
async def admin_authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "admin", "email": "a@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_admin_refresh_unknown_collection_404(api_client, admin_authed):
    r = await api_client.post("/api/admin/catalog/refresh/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_refresh_requires_admin(api_client):
    # Register two users; second is non-admin
    await api_client.post("/api/auth/register", json={
        "username": "first", "email": "f@x.com", "password": "Hunter2!secret",
    })
    api_client.cookies.clear()
    await api_client.post("/api/auth/register", json={
        "username": "second", "email": "s@x.com", "password": "Hunter2!secret",
    })
    r = await api_client.post("/api/admin/catalog/refresh/trending-day")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_refresh_runs_when_admin(api_client, admin_authed):
    with patch("streamload.api.routes.catalog._refresh_one") as mk:
        mk.return_value = AsyncMock(return_value=None)
        r = await api_client.post("/api/admin/catalog/refresh/trending-day")
        assert r.status_code in (200, 202)
```

- [ ] **Step 2: Run, expect FAIL**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_admin_refresh.py -v
```

- [ ] **Step 3: Append to `streamload/api/routes/catalog.py`**

```python
import asyncio
import os

import httpx
from fastapi import BackgroundTasks

from streamload.api.deps import AdminUser
from streamload.catalog.collections import get_collection_def
from streamload.catalog.tmdb import TmdbClient
from streamload.catalog.ingest import ingest_collection


async def _refresh_one(collection_id: str, db) -> None:
    cdef = get_collection_def(collection_id)
    if cdef is None:
        return
    api_key = os.environ.get("TMDB_API_KEY", "")
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        items = await cdef.fetch(tmdb)
    # Load services
    from streamload.services import ServiceRegistry, load_services
    from streamload.utils.http import HttpClient
    load_services()
    services = [cls(HttpClient()) for cls in ServiceRegistry.get_all()]
    await ingest_collection(
        db, collection_id=cdef.id, collection_title=cdef.title,
        media_type=cdef.media_type, sort_order=cdef.sort_order,
        refresh_ttl_hours=cdef.refresh_ttl_hours,
        items=items, services=services,
    )


admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.post("/catalog/refresh/{collection_id}", status_code=202)
async def admin_refresh(
    collection_id: str, db: SessionDep, user: AdminUser,
    background: BackgroundTasks,
) -> dict[str, str]:
    cdef = get_collection_def(collection_id)
    if cdef is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown collection")
    background.add_task(_refresh_one, collection_id, db)
    return {"status": "scheduled", "collection_id": collection_id}
```

(Add the `admin_router` to the file's exports.)

- [ ] **Step 4: Wire admin_router in `app.py`**

```python
from .routes.catalog import admin_router as catalog_admin_router
# in create_app:
app.include_router(catalog_admin_router, prefix="/api")
```

- [ ] **Step 5: Bump version**

Edit `streamload/version.py`:
```python
__version__ = "0.2.0-alpha.2"
```

- [ ] **Step 6: Run, expect PASS**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_admin_refresh.py -v
```
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add streamload/api/routes/catalog.py streamload/api/app.py streamload/version.py tests/api/test_admin_refresh.py
git commit -m "feat(api): admin endpoint to force-refresh a collection"
```

---

## Task 13: Final integration test + merge

- [ ] **Step 1: Run full suite**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest -q
```
Expected: all green (Plan 1 + Plan 2 tests).

- [ ] **Step 2: Manual smoke test**

```bash
# In one terminal:
DATABASE_URL=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload \
  TMDB_API_KEY=<your-key> \
  venv/bin/python streamload.py --api

# In another:
curl -X POST http://127.0.0.1:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"test","email":"t@x.com","password":"Hunter2!secret"}' \
  -c /tmp/cookies.txt

curl http://127.0.0.1:8000/api/collections -b /tmp/cookies.txt
# Expected: empty list

# Trigger an admin refresh
curl -X POST http://127.0.0.1:8000/api/admin/catalog/refresh/trending-day -b /tmp/cookies.txt
# Wait ~30 seconds

curl http://127.0.0.1:8000/api/collections -b /tmp/cookies.txt
# Expected: trending-day listed

curl http://127.0.0.1:8000/api/collections/trending-day -b /tmp/cookies.txt
# Expected: list of 20 items with poster_url
```

- [ ] **Step 3: Commit any test fixes**

```bash
git add -A
git commit -m "test: smoke-test catalog ingestion end-to-end" || true
```

- [ ] **Step 4: Merge**

```bash
git checkout main
git merge --no-ff feat/v2-catalog-ranker -m "Merge branch 'feat/v2-catalog-ranker'

Plan 2 of Streamload v2: TMDB-driven catalog with reverse lookup.

Includes:
* 5 new Postgres tables (catalog_items, catalog_sources, collections, collection_items, tv_episodes)
* TMDB v3 async client (popular, trending, top-rated, search, by-genre, anime)
* Title fuzzy matcher (rapidfuzz, normalized, year-aware)
* 8 collection definitions for home rows
* Catalog ingestion orchestrator (parallel reverse lookup, 8 concurrent)
* Source ranker (quality + latency + reliability + audio + subs match)
* /api/catalog/{tmdb_id}, /api/collections, /api/collections/{id}, /api/search
* Admin refresh endpoint + background worker

Spec: §6.1 + §6.2
Plan: docs/superpowers/plans/2026-05-08-streamload-v2-plan-2-catalog-ranker.md"

git push origin main
git tag -a v0.2.0-alpha.2 -m "Streamload v0.2.0-alpha.2 (Plan 2 complete)"
git push origin v0.2.0-alpha.2
```

---

## Self-Review Checklist

- [ ] All 13 tasks completed and committed
- [ ] `pytest -q` shows all green (Plan 1 + Plan 2)
- [ ] `/api/collections`, `/api/collections/{id}`, `/api/catalog/{id}` return expected shapes
- [ ] Admin can trigger collection refresh
- [ ] TMDB API key in `.env` used; client localized to it-IT
- [ ] No `Co-Authored-By` trailers
- [ ] Version bumped to v0.2.0-alpha.2

---

## Open issues (post-Plan-2, deferred)

- Source quality probing (currently `quality_max_height` is None until Plan 3 streaming proxy fills it in)
- Latency tracking (Plan 3 will populate `latency_ttfb_ms` from real measurements)
- TV episode list endpoint (Plan 4 needs it for the player)
- Image proxy/cache (Plan 4 frontend will use TMDB CDN directly for v1; Plan 5 may add local image proxy for offline-able PWA)
