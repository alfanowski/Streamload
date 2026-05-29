# Catalog Playability Curation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rank catalog rows so plugin-playable titles float to the top (soft-priority, stable bucket sort) and fix Anime rows surfacing Western cartoons instead of Japanese anime.

**Architecture:** Backend-centric ranking. The four `/rows/*` endpoints pass their TMDB results through a pure scorer (`playability.py`) before serving. Phase 1 = heuristic score (origin/language/popularity/recency, no extra round-trips) + anime JP-origin fix + stable bucket sort. Phase 2 = a `title_availability` crowd table, a report endpoint, client fire-and-forget hooks (probe weak / playback strong), and a crowd score layered onto the heuristic.

**Tech Stack:** Backend — Python/FastAPI, SQLAlchemy + Alembic, pytest, `venv/bin/python`. Client — Flutter, freezed, riverpod, dio.

**Spec:** `docs/superpowers/specs/2026-05-29-catalog-playability-curation-design.md`

---

## File Structure

**Phase 1 (backend `/Users/alfanowski/Desktop/Projects/Streamload`):**
- Create `streamload/catalog/playability.py` — `heuristic_score()` + `rank_by_playability()`. Pure, no IO.
- Modify `streamload/catalog/tmdb.py` — extend `TmdbItem` with `original_language`, `origin_country`, `vote_count`, `popularity`; populate in `_parse_movie`/`_parse_tv`; add `origin` param to `discover_by_genre`.
- Modify `streamload/api/routes/catalog.py` — wire `rank_by_playability` into the four `/rows/*` endpoints; add `origin` query param to `/rows/by-genre`.
- Create `tests/catalog/test_playability.py`.
- Modify `tests/api/test_catalog.py`, `tests/catalog/test_tmdb.py`.

**Phase 1 (client `/Users/alfanowski/Desktop/Projects/Streamload-Client`):**
- Modify `lib/state/home_rows_provider.dart` — `GenreRowKey` gets `origin`; `byGenreProvider` forwards it.
- Modify `lib/data/remote/endpoints/catalog_rows_api.dart` — `byGenre()` gets `origin`.
- Modify `lib/presentation/pages/home_page.dart` — anime rows pass `origin: 'jp'`.

**Phase 2 (backend):**
- Modify `streamload/db/models.py` — `TitleAvailability` model.
- Create `alembic/versions/<rev>_title_availability.py` (generated).
- Create `streamload/api/routes/availability.py` — `POST /api/availability/report`.
- Modify `streamload/api/app.py` — register the router.
- Modify `streamload/catalog/playability.py` — `crowd_score()` + fold into `rank_by_playability`.
- Modify `streamload/api/routes/catalog.py` — load crowd map, pass to ranker.
- Create `tests/api/test_availability.py`; extend `tests/catalog/test_playability.py`.

**Phase 2 (client):**
- Create `lib/data/remote/endpoints/availability_api.dart` — `AvailabilityApi.report()`.
- Create `lib/state/availability_reporter.dart` — `AvailabilityReporter` (fire-and-forget + per-session dedup) + provider.
- Modify `lib/plugins/routing/router.dart` — probe hook.
- Modify `lib/domain/play_title.dart` + `lib/state/play_controller_provider.dart` — playback hook.
- Create `test/data/remote/availability_api_test.dart`, `test/state/availability_reporter_test.dart`.

---

# PHASE 1 — Heuristic + Anime fix + Bucket sort

### Task 1: Extend TmdbItem with scorer fields

**Files:**
- Modify: `streamload/catalog/tmdb.py` (the `TmdbItem` dataclass ~line 35; `_parse_movie` ~line 114; `_parse_tv` ~line 129)
- Test: `tests/catalog/test_tmdb.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/catalog/test_tmdb.py`:

```python
@pytest.mark.asyncio
async def test_parse_movie_populates_scorer_fields():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            {"id": 1, "title": "Foo", "release_date": "2024-01-01",
             "poster_path": "/p.jpg", "original_language": "en",
             "origin_country": ["US"], "vote_count": 1200, "popularity": 88.5},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    items = await client.popular_movies()
    it = items[0]
    assert it.original_language == "en"
    assert it.origin_country == ["US"]
    assert it.vote_count == 1200
    assert it.popularity == 88.5


@pytest.mark.asyncio
async def test_parse_tv_origin_country_falls_back_to_empty():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            {"id": 2, "name": "Bar", "first_air_date": "2023-01-01",
             "poster_path": "/q.jpg"},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    items = await client.popular_tv()
    assert items[0].origin_country == []
    assert items[0].vote_count == 0
    assert items[0].popularity == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/catalog/test_tmdb.py::test_parse_movie_populates_scorer_fields -v`
Expected: FAIL with `AttributeError: 'TmdbItem' object has no attribute 'original_language'`.

- [ ] **Step 3: Extend the dataclass**

In `streamload/catalog/tmdb.py`, add fields to `TmdbItem` (after `genres`):

```python
    original_language: Optional[str] = None
    origin_country: list[str] = field(default_factory=list)
    vote_count: int = 0
    popularity: float = 0.0
```

- [ ] **Step 4: Populate in both parsers**

In `_parse_movie`, add to the `TmdbItem(...)` constructor (movies use `origin_country` when present, else derive nothing):

```python
            original_language=data.get("original_language"),
            origin_country=list(data.get("origin_country") or []),
            vote_count=int(data.get("vote_count") or 0),
            popularity=float(data.get("popularity") or 0.0),
```

In `_parse_tv`, add the identical four lines to its `TmdbItem(...)` constructor.

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/catalog/test_tmdb.py -v`
Expected: PASS (all, including the two new).

- [ ] **Step 6: Commit**

```bash
git add streamload/catalog/tmdb.py tests/catalog/test_tmdb.py
git commit -m "tmdb: TmdbItem carries original_language/origin_country/vote_count/popularity"
```

---

### Task 2: heuristic_score

**Files:**
- Create: `streamload/catalog/playability.py`
- Test: `tests/catalog/test_playability.py`

- [ ] **Step 1: Write the failing test**

Create `tests/catalog/test_playability.py`:

```python
from streamload.catalog.playability import heuristic_score
from streamload.catalog.tmdb import TmdbItem


def _item(**kw) -> TmdbItem:
    base = dict(
        tmdb_id=1, media_type="movie", title="X",
        original_language="en", origin_country=["US"],
        vote_count=500, popularity=50.0, year=2024,
    )
    base.update(kw)
    return TmdbItem(**base)


def test_western_movie_beats_eastern_movie():
    west = _item(origin_country=["US"], original_language="en")
    east = _item(origin_country=["KR"], original_language="ko")
    assert heuristic_score(west) > heuristic_score(east)


def test_italian_or_english_language_boosts():
    it = _item(original_language="it")
    de = _item(original_language="de")
    assert heuristic_score(it) > heuristic_score(de)


def test_popular_beats_obscure():
    popular = _item(vote_count=5000, popularity=200.0)
    obscure = _item(vote_count=2, popularity=0.3)
    assert heuristic_score(popular) > heuristic_score(obscure)


def test_anime_row_flips_origin_preference():
    jp = _item(media_type="tv", origin_country=["JP"], original_language="ja")
    us = _item(media_type="tv", origin_country=["US"], original_language="en")
    # In an anime row, JP origin should score the origin points, US should not.
    assert heuristic_score(jp, is_anime_row=True) > heuristic_score(us, is_anime_row=True)
    # And in a normal row the preference is reversed.
    assert heuristic_score(us, is_anime_row=False) > heuristic_score(jp, is_anime_row=False)


def test_missing_fields_do_not_crash_and_score_low():
    bare = TmdbItem(tmdb_id=9, media_type="movie", title="Bare")
    s = heuristic_score(bare)
    assert 0.0 <= s <= 100.0


def test_score_is_bounded_0_100():
    maxed = _item(vote_count=100000, popularity=9999.0, original_language="it",
                  origin_country=["IT"], year=2025)
    s = heuristic_score(maxed)
    assert 0.0 <= s <= 100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/catalog/test_playability.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'streamload.catalog.playability'`.

- [ ] **Step 3: Implement the scorer**

Create `streamload/catalog/playability.py`:

```python
"""Catalog playability ranking — pure scoring, no IO.

Soft-priority: we never hide titles, we sort the plugin-playable-likely ones
to the top of each row. The heuristic is a cold-start prior using only fields
already present in the TMDB discover/trending payload (no extra round-trips).
A crowd-sourced score (Phase 2) layers on top of this.

See docs/superpowers/specs/2026-05-29-catalog-playability-curation-design.md
"""
from __future__ import annotations

import math

from streamload.catalog.tmdb import TmdbItem

# Countries the Italian plugins (sc / au / rai) actually cover, mirroring
# tmdb._WESTERN_COUNTRIES. Kept as a set here for O(1) membership.
_WESTERN = {
    "US", "GB", "IT", "FR", "ES", "DE", "CA", "AU", "IE",
    "NL", "BE", "SE", "NO", "DK", "FI", "PT", "CH", "AT", "NZ",
}
_PREFERRED_LANGS = {"it", "en"}

# Weights sum to 100. Documented in the spec § "Heuristic scorer".
_W_ORIGIN = 40.0
_W_LANG = 20.0
_W_VOTES = 20.0
_W_POPULARITY = 12.0
_W_RECENCY = 8.0

# Caps so a single runaway field can't dominate the log-scaled terms.
_VOTE_CAP = 5000.0
_POPULARITY_CAP = 200.0
_RECENCY_YEARS = 3
# Current-ish year baseline for recency; recomputed per call from the item is
# overkill — titles only need "recent relative to now". We read the year off
# the item and compare to this constant, bumped at release time if needed.
_NOW_YEAR = 2026


def heuristic_score(item: TmdbItem, *, is_anime_row: bool = False) -> float:
    """0..100 prior that the IT plugins can play this title.

    ``is_anime_row`` flips the origin preference: anime rows reward JP origin,
    normal rows reward Western origin (matching the discover Western filter).
    """
    score = 0.0

    # Origin (40)
    countries = set(item.origin_country or [])
    if is_anime_row:
        if "JP" in countries:
            score += _W_ORIGIN
    else:
        if countries & _WESTERN:
            score += _W_ORIGIN

    # Language (20)
    lang = (item.original_language or "").lower()
    if is_anime_row:
        if lang == "ja":
            score += _W_LANG
    else:
        if lang in _PREFERRED_LANGS:
            score += _W_LANG

    # Votes (20) — log-scaled, capped.
    votes = min(float(item.vote_count or 0), _VOTE_CAP)
    if votes > 0:
        score += _W_VOTES * (math.log1p(votes) / math.log1p(_VOTE_CAP))

    # Popularity (12) — normalized, capped.
    pop = min(float(item.popularity or 0.0), _POPULARITY_CAP)
    if pop > 0:
        score += _W_POPULARITY * (pop / _POPULARITY_CAP)

    # Recency (8) — released within the last _RECENCY_YEARS.
    if item.year and (_NOW_YEAR - item.year) <= _RECENCY_YEARS and item.year <= _NOW_YEAR + 1:
        score += _W_RECENCY

    return max(0.0, min(100.0, score))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/catalog/test_playability.py -v`
Expected: PASS (all 6).

- [ ] **Step 5: Commit**

```bash
git add streamload/catalog/playability.py tests/catalog/test_playability.py
git commit -m "playability: heuristic_score — origin/lang/votes/popularity/recency prior"
```

---

### Task 3: rank_by_playability (stable bucket sort)

**Files:**
- Modify: `streamload/catalog/playability.py`
- Test: `tests/catalog/test_playability.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/catalog/test_playability.py`:

```python
from streamload.catalog.playability import rank_by_playability


def test_bucket_sort_floats_playable_up_preserving_intra_order():
    # a, c are Western (high); b, d are Eastern (low). Input order a,b,c,d.
    a = _item(tmdb_id=1, origin_country=["US"], original_language="en")
    b = _item(tmdb_id=2, origin_country=["KR"], original_language="ko")
    c = _item(tmdb_id=3, origin_country=["GB"], original_language="en")
    d = _item(tmdb_id=4, origin_country=["JP"], original_language="ja")
    ranked = rank_by_playability([a, b, c, d])
    ids = [i.tmdb_id for i in ranked]
    # Bucket A (a, c) keeps its relative order, then bucket B (b, d) keeps its.
    assert ids == [1, 3, 2, 4]


def test_rank_preserves_all_items_no_drops():
    items = [_item(tmdb_id=i) for i in range(10)]
    ranked = rank_by_playability(items)
    assert sorted(i.tmdb_id for i in ranked) == list(range(10))


def test_anime_row_ranks_jp_first():
    jp = _item(tmdb_id=1, media_type="tv", origin_country=["JP"], original_language="ja")
    us = _item(tmdb_id=2, media_type="tv", origin_country=["US"], original_language="en")
    ranked = rank_by_playability([us, jp], is_anime_row=True)
    assert [i.tmdb_id for i in ranked] == [1, 2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/catalog/test_playability.py::test_bucket_sort_floats_playable_up_preserving_intra_order -v`
Expected: FAIL with `ImportError: cannot import name 'rank_by_playability'`.

- [ ] **Step 3: Implement the ranker**

Append to `streamload/catalog/playability.py`:

```python
# Items scoring >= this go in the "playable-likely" bucket. The heuristic
# midpoint: an item needs origin OR (language + some popularity) to clear it.
# Tunable; documented in the spec.
_BUCKET_THRESHOLD = 40.0


def rank_by_playability(
    items: list[TmdbItem],
    crowd_map: dict[tuple[int, str], "CrowdCounts"] | None = None,
    *,
    is_anime_row: bool = False,
) -> list[TmdbItem]:
    """Stable bucket sort: playable-likely items first (in original order),
    then the rest (in original order). NEVER drops or dedupes items.

    ``crowd_map`` is the Phase 2 signal (keyed by ``(tmdb_id, media_type)``);
    when None or empty the ranking is pure heuristic.
    """
    bucket_a: list[TmdbItem] = []
    bucket_b: list[TmdbItem] = []
    for it in items:
        total = heuristic_score(it, is_anime_row=is_anime_row)
        if crowd_map:
            counts = crowd_map.get((it.tmdb_id, it.media_type))
            if counts is not None:
                total += crowd_score(counts)
        (bucket_a if total >= _BUCKET_THRESHOLD else bucket_b).append(it)
    return bucket_a + bucket_b
```

Note: `crowd_score` and `CrowdCounts` are added in Phase 2 Task 9. For Phase 1 the `crowd_map` param defaults to `None` and the `if crowd_map:` branch is never taken, so the forward reference in the type hint (a string) is fine and the function works. To keep Phase 1 importable without `crowd_score` defined yet, add a module-level stub at the END of the Phase 1 file that Task 9 will replace:

```python
# --- Phase 2 placeholder (replaced in Task 9) -------------------------------
# Defined here so rank_by_playability imports cleanly in Phase 1. Task 9
# replaces both this and the CrowdCounts type with the real implementation.
class CrowdCounts:  # noqa: D401 - placeholder
    pass


def crowd_score(counts: "CrowdCounts") -> float:
    return 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/catalog/test_playability.py -v`
Expected: PASS (all 9).

- [ ] **Step 5: Commit**

```bash
git add streamload/catalog/playability.py tests/catalog/test_playability.py
git commit -m "playability: rank_by_playability stable bucket sort (+Phase2 stub)"
```

---

### Task 4: discover_by_genre gets an origin param

**Files:**
- Modify: `streamload/catalog/tmdb.py` (`discover_by_genre` ~line 151)
- Test: `tests/catalog/test_tmdb.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/catalog/test_tmdb.py`:

```python
@pytest.mark.asyncio
async def test_discover_by_genre_jp_origin_uses_jp_country():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            {"id": 1, "name": "Anime", "first_air_date": "2024-01-01",
             "poster_path": "/p.jpg", "vote_count": 100},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    await client.discover_by_genre(genre_ids=[16], media_type="tv", origin="jp")
    params = http.get.call_args.kwargs.get("params", {})
    assert params.get("with_origin_country") == "JP"


@pytest.mark.asyncio
async def test_discover_by_genre_western_origin_is_default():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mk_resp({
        "results": [
            {"id": 1, "title": "Film", "release_date": "2024-01-01",
             "poster_path": "/p.jpg", "vote_count": 100},
        ]
    }))
    client = TmdbClient(api_key="x", http=http)
    await client.discover_by_genre(genre_ids=[35], media_type="movie")
    params = http.get.call_args.kwargs.get("params", {})
    assert "|" in params.get("with_origin_country", "")  # the Western list
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/catalog/test_tmdb.py::test_discover_by_genre_jp_origin_uses_jp_country -v`
Expected: FAIL with `TypeError: discover_by_genre() got an unexpected keyword argument 'origin'`.

- [ ] **Step 3: Add the origin param**

In `streamload/catalog/tmdb.py`, change `discover_by_genre`'s signature to add `origin: str = "western"` (after `original_language`), and replace its `with_origin_country` line. The current body sets `"with_origin_country": _WESTERN_COUNTRIES`; make it conditional:

```python
    async def discover_by_genre(
        self,
        *,
        genre_ids: list[int],
        media_type: str,
        original_language: str | None = None,
        origin: str = "western",
        page: int = 1,
    ) -> list[TmdbItem]:
        if media_type not in ("movie", "tv"):
            raise ValueError("media_type must be 'movie' or 'tv'")
        country = "JP" if origin == "jp" else _WESTERN_COUNTRIES
        params: dict[str, Any] = {
            "with_genres": ",".join(str(g) for g in genre_ids),
            "with_origin_country": country,
            "vote_count.gte": _VOTE_FLOOR,
            "include_adult": "false",
            "sort_by": "popularity.desc",
            "page": page,
        }
        if original_language:
            params["with_original_language"] = original_language
        data = await self._get(f"/discover/{media_type}", params)
        parser = self._parse_movie if media_type == "movie" else self._parse_tv
        return _quality_filter([parser(x) for x in data.get("results", [])])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/catalog/test_tmdb.py -v`
Expected: PASS (all, including the two new + the pre-existing `test_discover_by_genre_movie_with_language`).

- [ ] **Step 5: Commit**

```bash
git add streamload/catalog/tmdb.py tests/catalog/test_tmdb.py
git commit -m "tmdb: discover_by_genre origin param (jp → JP origin, western default)"
```

---

### Task 5: Wire ranking + origin into the row endpoints

**Files:**
- Modify: `streamload/api/routes/catalog.py` (the four `/rows/*` handlers ~lines 308-420)
- Test: `tests/api/test_catalog.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/api/test_catalog.py` (uses the existing `api_client`, `authed`, `monkeypatch`, `_summary_item` helpers — match how `test_rows_caps_at_limit` is written):

```python
@pytest.mark.asyncio
async def test_rows_trending_ranks_playable_first(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    from streamload.catalog.tmdb import TmdbItem

    async def fake_week(self, *, media_type="all", page=1):
        if page > 1:
            return []
        # obscure Korean first, mainstream US second — ranker must flip them.
        return [
            TmdbItem(tmdb_id=1, media_type="movie", title="K",
                     origin_country=["KR"], original_language="ko",
                     vote_count=1, popularity=0.1, year=2024),
            TmdbItem(tmdb_id=2, media_type="movie", title="U",
                     origin_country=["US"], original_language="en",
                     vote_count=5000, popularity=180.0, year=2024),
        ]

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.trending_week", fake_week,
    )
    r = await api_client.get("/api/catalog/rows/trending")
    assert r.status_code == 200
    ids = [x["tmdb_id"] for x in r.json()]
    assert ids == [2, 1]  # US (playable-likely) floated above KR


@pytest.mark.asyncio
async def test_rows_by_genre_jp_origin_forwarded(api_client, authed, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    captured = {}

    async def fake_discover(self, *, genre_ids, media_type,
                            original_language=None, origin="western", page=1):
        captured["origin"] = origin
        return []

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.discover_by_genre", fake_discover,
    )
    r = await api_client.get(
        "/api/catalog/rows/by-genre?genre_ids=16&media_type=tv&origin=jp")
    assert r.status_code == 200
    assert captured["origin"] == "jp"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/api/test_catalog.py::test_rows_trending_ranks_playable_first -v`
Expected: FAIL (ids come back `[1, 2]` — unranked).

- [ ] **Step 3: Wire the ranker + origin param**

In `streamload/api/routes/catalog.py`:

Add the import near the top (with the other `streamload.catalog` imports):

```python
from streamload.catalog.playability import rank_by_playability
```

In `rows_trending`, after `items = await _collect_pages(...)` and before the `return`, insert:

```python
    items = rank_by_playability(items)
```

Same one-line insertion in `rows_new_releases` and `rows_top_rated` (after their `_collect_pages`, before `return`).

In `rows_by_genre`: add `origin: str = "western"` to the signature (after `original_language`), forward it into the lambda, and rank with the anime flag. Replace the body's fetch + return:

```python
    items = await _collect_pages(
        lambda p: tmdb.discover_by_genre(
            genre_ids=ids,
            media_type=media_type,
            original_language=original_language,
            origin=origin,
            page=p,
        ),
        limit=limit,
        start_page=page,
    )
    items = rank_by_playability(items, is_anime_row=(origin == "jp"))
    return [_to_summary(i) for i in items]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/api/test_catalog.py -v`
Expected: PASS (the two new + all pre-existing; `test_get_catalog_item_404` is the one known pre-existing failure — ignore it).

- [ ] **Step 5: Commit**

```bash
git add streamload/api/routes/catalog.py tests/api/test_catalog.py
git commit -m "catalog/rows: rank by playability + by-genre origin=jp param"
```

---

### Task 6: Client — GenreRowKey + byGenre forward origin

**Files:**
- Modify: `lib/data/remote/endpoints/catalog_rows_api.dart` (the abstract `byGenre` ~line 39 + the `HttpCatalogRowsApi.byGenre` impl ~line 105)
- Modify: `lib/state/home_rows_provider.dart` (`GenreRowKey` ~line 36; `byGenreProvider` ~line 123)
- Test: `test/data/remote/catalog_rows_api_test.dart`, `test/state/home_rows_provider_test.dart`

- [ ] **Step 1: Write the failing test**

Add to `test/data/remote/catalog_rows_api_test.dart` (match the existing mock-dio style in that file):

```dart
test('byGenre forwards origin=jp as a query param', () async {
  // ...arrange the mock ApiClient/dio used in this file to capture the query...
  await api.byGenre(genreIds: [16], mediaType: 'tv', origin: 'jp');
  expect(capturedQuery['origin'], 'jp');
});
```

Add to `test/state/home_rows_provider_test.dart`:

```dart
test('GenreRowKey equality includes origin', () {
  const a = GenreRowKey(genreIds: [16], mediaType: 'tv', origin: 'jp');
  const b = GenreRowKey(genreIds: [16], mediaType: 'tv', origin: 'jp');
  const c = GenreRowKey(genreIds: [16], mediaType: 'tv');
  expect(a, equals(b));
  expect(a, isNot(equals(c)));
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/alfanowski/Desktop/Projects/Streamload-Client && flutter test test/state/home_rows_provider_test.dart --no-pub`
Expected: FAIL (compile error — `origin` named param doesn't exist on `GenreRowKey`).

- [ ] **Step 3: Add origin to the API**

In `lib/data/remote/endpoints/catalog_rows_api.dart`, the abstract method:

```dart
  Future<List<MediaSummary>> byGenre({
    required List<int> genreIds,
    required String mediaType,
    String? originalLanguage,
    String origin = 'western',
  });
```

The `HttpCatalogRowsApi.byGenre` impl — add `origin` to the signature and the query map:

```dart
  @override
  Future<List<MediaSummary>> byGenre({
    required List<int> genreIds,
    required String mediaType,
    String? originalLanguage,
    String origin = 'western',
  }) async {
    final json = await _client.getJson('/api/catalog/rows/by-genre', query: {
      'genre_ids': genreIds.join(','),
      'media_type': mediaType,
      if (originalLanguage != null) 'original_language': originalLanguage,
      if (origin != 'western') 'origin': origin,
    });
    // ...existing parse of json into List<MediaSummary>...
  }
```

(Keep the existing response-parsing body below the query map unchanged.)

- [ ] **Step 4: Add origin to GenreRowKey + provider**

In `lib/state/home_rows_provider.dart`, `GenreRowKey`:

```dart
class GenreRowKey {
  const GenreRowKey({
    required this.genreIds,
    required this.mediaType,
    this.originalLanguage,
    this.origin = 'western',
  });

  final List<int> genreIds;
  final String mediaType;
  final String? originalLanguage;
  final String origin;

  @override
  bool operator ==(Object other) {
    if (other is! GenreRowKey) return false;
    if (other.mediaType != mediaType) return false;
    if (other.originalLanguage != originalLanguage) return false;
    if (other.origin != origin) return false;
    if (other.genreIds.length != genreIds.length) return false;
    for (var i = 0; i < genreIds.length; i++) {
      if (other.genreIds[i] != genreIds[i]) return false;
    }
    return true;
  }

  @override
  int get hashCode => Object.hash(
        mediaType,
        originalLanguage,
        origin,
        Object.hashAll(genreIds),
      );
}
```

`byGenreProvider` — forward the new field:

```dart
final byGenreProvider = FutureProvider.autoDispose
    .family<List<MediaSummary>, GenreRowKey>((ref, key) async {
  final api = await ref.watch(catalogRowsApiProvider.future);
  return api.byGenre(
    genreIds: key.genreIds,
    mediaType: key.mediaType,
    originalLanguage: key.originalLanguage,
    origin: key.origin,
  );
});
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `flutter test test/state/home_rows_provider_test.dart test/data/remote/catalog_rows_api_test.dart --no-pub`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add lib/data/remote/endpoints/catalog_rows_api.dart lib/state/home_rows_provider.dart test/
git commit -m "rows(client): GenreRowKey + byGenre carry origin param"
```

---

### Task 7: Client — anime rows pass origin=jp

**Files:**
- Modify: `lib/presentation/pages/home_page.dart` (`_buildAnimeRows`)
- Test: `test/pages/home_page_test.dart`

- [ ] **Step 1: Write the failing test**

Add to `test/pages/home_page_test.dart` a test that overrides `byGenreProvider` and asserts the anime page's first row requests a JP-origin key. Match the existing override pattern in that file:

```dart
testWidgets('anime rows request origin=jp', (tester) async {
  final requestedKeys = <GenreRowKey>[];
  // Override byGenreProvider to record the family key it was built with.
  // (Use ProviderScope overrides as the other tests in this file do; capture
  //  via an override that records `key` then returns an empty list.)
  // ...
  // pump HomePage(filter: 'anime') ...
  expect(
    requestedKeys.any((k) => k.genreIds.contains(16) && k.origin == 'jp'),
    isTrue,
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `flutter test test/pages/home_page_test.dart --no-pub`
Expected: FAIL (anime keys currently have `origin == 'western'`).

- [ ] **Step 3: Add origin: 'jp' to every anime GenreRowKey**

In `lib/presentation/pages/home_page.dart` `_buildAnimeRows`, add `origin: 'jp'` to each `GenreRowKey(...)` constructor. Example for the first row:

```dart
        provider: byGenreProvider(const GenreRowKey(
          genreIds: [16],
          mediaType: 'tv',
          origin: 'jp',
        )),
```

Repeat for all anime `GenreRowKey(...)` instances in `_buildAnimeRows` (the `[16, 10759]`, `[16, 10765]`, and any others).

- [ ] **Step 4: Run tests to verify they pass**

Run: `flutter test test/pages/home_page_test.dart --no-pub`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/presentation/pages/home_page.dart test/pages/home_page_test.dart
git commit -m "home: anime rows request JP origin (no more Western cartoons)"
```

---

### Task 8: Phase 1 verification

- [ ] **Step 1: Backend full suite**

Run: `cd /Users/alfanowski/Desktop/Projects/Streamload && venv/bin/python -m pytest -q`
Expected: all pass except the single known pre-existing `test_get_catalog_item_404`.

- [ ] **Step 2: Client analyze + test**

Run: `cd /Users/alfanowski/Desktop/Projects/Streamload-Client && flutter analyze --no-pub && flutter test --no-pub`
Expected: analyze clean of errors; tests ≥ 429 passing.

- [ ] **Step 3: Manual smoke (operator)**

Start backend + client, open `/anime` → rows show Japanese anime (not Western cartoons). Open Home → playable-looking mainstream titles sit at the top of each row.

---

# PHASE 2 — Crowd-sourced layer

### Task 9: crowd_score + CrowdCounts (replace Phase 1 stub)

**Files:**
- Modify: `streamload/catalog/playability.py` (replace the Phase 1 placeholder block)
- Test: `tests/catalog/test_playability.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/catalog/test_playability.py`:

```python
from streamload.catalog.playability import CrowdCounts, crowd_score, rank_by_playability


def test_crowd_score_weights_play_3x_probe():
    play_only = CrowdCounts(probe_count=0, play_count=10)
    probe_only = CrowdCounts(probe_count=10, play_count=0)
    assert crowd_score(play_only) > crowd_score(probe_only)


def test_crowd_score_zero_when_no_counts():
    assert crowd_score(CrowdCounts(probe_count=0, play_count=0)) == 0.0


def test_crowd_signal_can_outrank_heuristic():
    # An obscure Korean title that someone actually played should beat a
    # mainstream-but-never-played US title.
    obscure = _item(tmdb_id=1, origin_country=["KR"], original_language="ko",
                    vote_count=1, popularity=0.1)
    mainstream = _item(tmdb_id=2, origin_country=["US"], original_language="en",
                       vote_count=5000, popularity=180.0)
    crowd = {(1, "movie"): CrowdCounts(probe_count=2, play_count=20)}
    ranked = rank_by_playability([mainstream, obscure], crowd)
    assert ranked[0].tmdb_id == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/catalog/test_playability.py::test_crowd_score_weights_play_3x_probe -v`
Expected: FAIL (`CrowdCounts` is the empty placeholder with no fields).

- [ ] **Step 3: Replace the placeholder block**

In `streamload/catalog/playability.py`, replace the Phase 1 placeholder (`class CrowdCounts: pass` + the `crowd_score` returning 0.0) with:

```python
from dataclasses import dataclass

# Crowd score caps at ~30 points so a strong usage signal can lift an item
# over the bucket threshold but never swamps the heuristic entirely.
_CROWD_CAP = 30.0
_PLAY_WEIGHT = 3.0
_PROBE_WEIGHT = 1.0


@dataclass
class CrowdCounts:
    probe_count: int = 0
    play_count: int = 0


def crowd_score(counts: CrowdCounts) -> float:
    raw = counts.play_count * _PLAY_WEIGHT + counts.probe_count * _PROBE_WEIGHT
    if raw <= 0:
        return 0.0
    # log-scale + cap so 20 plays ≈ near the cap, 2 probes ≈ a nudge.
    return min(_CROWD_CAP, _CROWD_CAP * (math.log1p(raw) / math.log1p(100.0)))
```

Move the `from dataclasses import dataclass` to the top imports if the file style prefers (the codebase imports at top — relocate it next to `import math`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/catalog/test_playability.py -v`
Expected: PASS (all, including the three new).

- [ ] **Step 5: Commit**

```bash
git add streamload/catalog/playability.py tests/catalog/test_playability.py
git commit -m "playability: real crowd_score (play 3x probe, log-capped at 30)"
```

---

### Task 10: TitleAvailability model + migration

**Files:**
- Modify: `streamload/db/models.py` (add after the `CatalogItem` block ~line 214)
- Create: `alembic/versions/<rev>_title_availability.py` (generated)
- Test: `tests/api/test_availability.py` (created in Task 12 — model is exercised there)

- [ ] **Step 1: Add the model**

In `streamload/db/models.py`, add (match the existing model style — `Mapped`/`mapped_column`, timezone-aware timestamps):

```python
class TitleAvailability(Base):
    __tablename__ = "title_availability"

    tmdb_id: Mapped[int] = mapped_column(primary_key=True)
    media_type: Mapped[str] = mapped_column(primary_key=True)
    probe_count: Mapped[int] = mapped_column(default=0, server_default="0")
    play_count: Mapped[int] = mapped_column(default=0, server_default="0")
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "media_type IN ('movie', 'tv')",
            name="ck_title_availability_media_type",
        ),
    )
```

Confirm `datetime`, `DateTime`, `func`, `CheckConstraint`, `Mapped`, `mapped_column` are already imported at the top of `models.py` (the existing models use them — they are).

- [ ] **Step 2: Generate the migration**

Run:
```bash
cd /Users/alfanowski/Desktop/Projects/Streamload
venv/bin/alembic revision --autogenerate -m "title_availability"
```
Expected: a new file under `alembic/versions/` creating the `title_availability` table. Open it and verify it has `op.create_table("title_availability", ...)` with the two-column PK + the two counters + `last_seen_at` + the check constraint. If autogenerate missed the check constraint, add it manually.

- [ ] **Step 3: Apply the migration**

Run: `venv/bin/alembic upgrade head`
Expected: `Running upgrade ... title_availability`. No error.

- [ ] **Step 4: Verify the table exists**

Run: `psql postgresql://streamload:streamload@127.0.0.1:5432/streamload -c "\d title_availability"`
Expected: the table with `tmdb_id, media_type` PK, `probe_count`, `play_count`, `last_seen_at`.

- [ ] **Step 5: Commit**

```bash
git add streamload/db/models.py alembic/versions/
git commit -m "db: title_availability table (crowd-sourced playability counters)"
```

---

### Task 11: availability_dao — UPSERT helper

**Files:**
- Create: `streamload/catalog/availability_dao.py`
- Test: `tests/catalog/test_availability_dao.py`

- [ ] **Step 1: Write the failing test**

Create `tests/catalog/test_availability_dao.py` (match how other DAO/DB tests in `tests/` get an async session — reuse the existing test DB session fixture; check `tests/conftest.py` for the fixture name, e.g. `db_session`):

```python
import pytest

from streamload.catalog.availability_dao import (
    record_event, load_crowd_map,
)


@pytest.mark.asyncio
async def test_record_probe_then_play_accumulates(db_session):
    await record_event(db_session, tmdb_id=5, media_type="movie", kind="probe")
    await record_event(db_session, tmdb_id=5, media_type="movie", kind="play")
    await record_event(db_session, tmdb_id=5, media_type="movie", kind="play")
    await db_session.commit()
    crowd = await load_crowd_map(db_session, [(5, "movie")])
    counts = crowd[(5, "movie")]
    assert counts.probe_count == 1
    assert counts.play_count == 2


@pytest.mark.asyncio
async def test_load_crowd_map_empty_for_unknown(db_session):
    crowd = await load_crowd_map(db_session, [(999, "movie")])
    assert crowd == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/catalog/test_availability_dao.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement the DAO**

Create `streamload/catalog/availability_dao.py`:

```python
"""Read/write helpers for the title_availability crowd table."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.catalog.playability import CrowdCounts
from streamload.db.models import TitleAvailability


async def record_event(
    session: AsyncSession,
    *,
    tmdb_id: int,
    media_type: str,
    kind: str,
) -> None:
    """UPSERT: increment probe_count (kind='probe') or play_count
    (kind='play') for (tmdb_id, media_type), bumping last_seen_at."""
    if kind not in ("probe", "play"):
        raise ValueError("kind must be 'probe' or 'play'")
    col = "probe_count" if kind == "probe" else "play_count"
    stmt = pg_insert(TitleAvailability).values(
        tmdb_id=tmdb_id,
        media_type=media_type,
        probe_count=1 if kind == "probe" else 0,
        play_count=1 if kind == "play" else 0,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["tmdb_id", "media_type"],
        set_={
            col: getattr(TitleAvailability, col) + 1,
            "last_seen_at": stmt.excluded.last_seen_at,
        },
    )
    await session.execute(stmt)


async def load_crowd_map(
    session: AsyncSession,
    keys: list[tuple[int, str]],
) -> dict[tuple[int, str], CrowdCounts]:
    """Return {(tmdb_id, media_type): CrowdCounts} for the given keys.
    Keys with no row are omitted."""
    if not keys:
        return {}
    ids = {k[0] for k in keys}
    rows = (
        await session.execute(
            select(TitleAvailability).where(TitleAvailability.tmdb_id.in_(ids))
        )
    ).scalars().all()
    wanted = set(keys)
    out: dict[tuple[int, str], CrowdCounts] = {}
    for r in rows:
        key = (r.tmdb_id, r.media_type)
        if key in wanted:
            out[key] = CrowdCounts(
                probe_count=r.probe_count, play_count=r.play_count
            )
    return out
```

Note: `last_seen_at` uses the column server_default on insert; on update we re-set it via `stmt.excluded.last_seen_at` which carries the default-evaluated value. If the dialect doesn't surface excluded default cleanly, replace that set entry with `"last_seen_at": func.now()` and `from sqlalchemy import func`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/catalog/test_availability_dao.py -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add streamload/catalog/availability_dao.py tests/catalog/test_availability_dao.py
git commit -m "availability: DAO record_event UPSERT + load_crowd_map"
```

---

### Task 12: POST /api/availability/report

**Files:**
- Create: `streamload/api/routes/availability.py`
- Modify: `streamload/api/app.py` (register router)
- Test: `tests/api/test_availability.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_availability.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_report_probe_increments(api_client, authed):
    r = await api_client.post("/api/availability/report", json={
        "tmdb_id": 7, "media_type": "movie", "kind": "probe",
    })
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_report_rejects_bad_kind(api_client, authed):
    r = await api_client.post("/api/availability/report", json={
        "tmdb_id": 7, "media_type": "movie", "kind": "nope",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_report_rejects_bad_media_type(api_client, authed):
    r = await api_client.post("/api/availability/report", json={
        "tmdb_id": 7, "media_type": "podcast", "kind": "probe",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_report_requires_auth(api_client):
    r = await api_client.post("/api/availability/report", json={
        "tmdb_id": 7, "media_type": "movie", "kind": "probe",
    })
    assert r.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/api/test_availability.py -v`
Expected: FAIL (404 — route doesn't exist).

- [ ] **Step 3: Implement the route**

Create `streamload/api/routes/availability.py`:

```python
"""Crowd-sourced playability reporting — clients post probe/playback events."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from streamload.api.deps import CurrentUser, SessionDep
from streamload.catalog.availability_dao import record_event

router = APIRouter(prefix="/availability", tags=["availability"])


class AvailabilityReport(BaseModel):
    tmdb_id: int
    media_type: Literal["movie", "tv"]
    kind: Literal["probe", "playback"]


@router.post("/report", status_code=status.HTTP_204_NO_CONTENT)
async def report(
    body: AvailabilityReport,
    user: CurrentUser,
    db: SessionDep,
) -> Response:
    # Map the client's "playback" wire word to the DAO's "play" kind.
    dao_kind = "play" if body.kind == "playback" else "probe"
    await record_event(
        db, tmdb_id=body.tmdb_id, media_type=body.media_type, kind=dao_kind
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

In `streamload/api/app.py`, import and register (match how the existing routers are included, e.g. `app.include_router(catalog.router, prefix="/api")`):

```python
from streamload.api.routes import availability
# ...
app.include_router(availability.router, prefix="/api")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/api/test_availability.py -v`
Expected: PASS (all 4).

- [ ] **Step 5: Commit**

```bash
git add streamload/api/routes/availability.py streamload/api/app.py tests/api/test_availability.py
git commit -m "api: POST /api/availability/report (probe/playback crowd events)"
```

---

### Task 13: Row endpoints load the crowd map

**Files:**
- Modify: `streamload/api/routes/catalog.py` (the four `/rows/*` handlers + `SessionDep`)
- Test: `tests/api/test_catalog.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/api/test_catalog.py`:

```python
@pytest.mark.asyncio
async def test_rows_trending_crowd_outranks_heuristic(
        api_client, authed, db_session, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    from streamload.catalog.tmdb import TmdbItem
    from streamload.catalog.availability_dao import record_event

    # tmdb_id 1 is obscure (low heuristic) but heavily played.
    await record_event(db_session, tmdb_id=1, media_type="movie", kind="play")
    for _ in range(20):
        await record_event(db_session, tmdb_id=1, media_type="movie", kind="play")
    await db_session.commit()

    async def fake_week(self, *, media_type="all", page=1):
        if page > 1:
            return []
        return [
            TmdbItem(tmdb_id=1, media_type="movie", title="Obscure",
                     origin_country=["KR"], original_language="ko",
                     vote_count=1, popularity=0.1, year=2024),
            TmdbItem(tmdb_id=2, media_type="movie", title="Mainstream",
                     origin_country=["US"], original_language="en",
                     vote_count=5000, popularity=180.0, year=2024),
        ]

    monkeypatch.setattr(
        "streamload.api.routes.catalog.TmdbClient.trending_week", fake_week,
    )
    r = await api_client.get("/api/catalog/rows/trending")
    ids = [x["tmdb_id"] for x in r.json()]
    assert ids[0] == 1  # crowd-played obscure title floats above mainstream
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/api/test_catalog.py::test_rows_trending_crowd_outranks_heuristic -v`
Expected: FAIL (ids[0] == 2 — crowd map not loaded yet).

- [ ] **Step 3: Load + pass the crowd map**

In `streamload/api/routes/catalog.py`:

Add the import:

```python
from streamload.catalog.availability_dao import load_crowd_map
```

Add `db: SessionDep` to each of the four `/rows/*` handler signatures (after `user: CurrentUser`). `SessionDep` is already imported in this module (used by other handlers); confirm and add the import if missing.

Replace each `items = rank_by_playability(items[, is_anime_row=...])` with a crowd-aware version. Helper to keep it DRY — add near `_to_summary`:

```python
async def _rank_with_crowd(db, items, *, is_anime_row=False):
    keys = [(i.tmdb_id, i.media_type) for i in items]
    crowd = await load_crowd_map(db, keys)
    return rank_by_playability(items, crowd, is_anime_row=is_anime_row)
```

Then in each handler:
- `rows_trending`: `items = await _rank_with_crowd(db, items)`
- `rows_new_releases`: `items = await _rank_with_crowd(db, items)`
- `rows_top_rated`: `items = await _rank_with_crowd(db, items)`
- `rows_by_genre`: `items = await _rank_with_crowd(db, items, is_anime_row=(origin == "jp"))`

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/api/test_catalog.py -v`
Expected: PASS (the new + all pre-existing curation tests from Task 5; `test_get_catalog_item_404` still the only known failure).

- [ ] **Step 5: Commit**

```bash
git add streamload/api/routes/catalog.py tests/api/test_catalog.py
git commit -m "catalog/rows: fold crowd map into playability ranking"
```

---

### Task 14: Client — AvailabilityApi

**Files:**
- Create: `lib/data/remote/endpoints/availability_api.dart`
- Modify: `lib/state/api_client_provider.dart` (add provider — match existing endpoint provider pattern)
- Test: `test/data/remote/availability_api_test.dart`

- [ ] **Step 1: Write the failing test**

Create `test/data/remote/availability_api_test.dart` (match the mock-dio/ApiClient style used in `test/data/remote/search_api_test.dart`):

```dart
import 'package:flutter_test/flutter_test.dart';
// ...imports + a mock ApiClient that captures the POST path + body...

void main() {
  test('report posts kind+tmdbId+mediaType to /api/availability/report',
      () async {
    // arrange mock client capturing postJson(path, body)
    await api.report(tmdbId: 42, mediaType: 'movie', kind: 'playback');
    expect(capturedPath, '/api/availability/report');
    expect(capturedBody, {
      'tmdb_id': 42, 'media_type': 'movie', 'kind': 'playback',
    });
  });
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `flutter test test/data/remote/availability_api_test.dart --no-pub`
Expected: FAIL (file/class doesn't exist).

- [ ] **Step 3: Implement the API**

Create `lib/data/remote/endpoints/availability_api.dart`:

```dart
// lib/data/remote/endpoints/availability_api.dart
import '../api_client.dart';

/// Posts crowd-sourced playability signals. Fire-and-forget at the call
/// sites — see AvailabilityReporter.
class AvailabilityApi {
  AvailabilityApi(this._client);
  final ApiClient _client;

  /// kind is 'probe' (weak) or 'playback' (strong).
  Future<void> report({
    required int tmdbId,
    required String mediaType,
    required String kind,
  }) async {
    await _client.postJson('/api/availability/report', {
      'tmdb_id': tmdbId,
      'media_type': mediaType,
      'kind': kind,
    });
  }
}
```

In `lib/state/api_client_provider.dart`, add a provider mirroring the others (e.g. `searchApiProvider`):

```dart
final availabilityApiProvider = FutureProvider<AvailabilityApi>((ref) async {
  final client = await ref.watch(apiClientProvider.future);
  return AvailabilityApi(client);
});
```

(Add the import for `availability_api.dart`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `flutter test test/data/remote/availability_api_test.dart --no-pub`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/data/remote/endpoints/availability_api.dart lib/state/api_client_provider.dart test/
git commit -m "data(availability): AvailabilityApi.report + provider"
```

---

### Task 15: Client — AvailabilityReporter (fire-and-forget + dedup)

**Files:**
- Create: `lib/state/availability_reporter.dart`
- Test: `test/state/availability_reporter_test.dart`

- [ ] **Step 1: Write the failing test**

Create `test/state/availability_reporter_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
// ...import AvailabilityReporter + a fake AvailabilityApi recording calls...

void main() {
  test('reports probe + playback once per session per (id,type,kind)', () async {
    final fake = _RecordingApi();
    final reporter = AvailabilityReporter(fake);
    reporter.reportProbe(42, 'movie');
    reporter.reportProbe(42, 'movie'); // deduped
    reporter.reportPlayback(42, 'movie');
    await Future<void>.delayed(Duration.zero); // let fire-and-forget run
    expect(fake.calls, [
      ('probe', 42, 'movie'),
      ('playback', 42, 'movie'),
    ]);
  });

  test('a failing report never throws to the caller', () async {
    final reporter = AvailabilityReporter(_ThrowingApi());
    // Must not throw.
    reporter.reportPlayback(1, 'tv');
    await Future<void>.delayed(Duration.zero);
  });
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `flutter test test/state/availability_reporter_test.dart --no-pub`
Expected: FAIL (class doesn't exist).

- [ ] **Step 3: Implement the reporter**

Create `lib/state/availability_reporter.dart`:

```dart
// lib/state/availability_reporter.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/remote/endpoints/availability_api.dart';
import '../infra/logger.dart';
import 'api_client_provider.dart';

final _log = Logger('availability.reporter');

/// Fire-and-forget crowd-signal reporter. Dedupes per session so we don't
/// spam the backend with repeated probes/plays of the same title, and never
/// lets a failed report surface to the caller (it must not break playback).
class AvailabilityReporter {
  AvailabilityReporter(this._api);
  final AvailabilityApi _api;
  final Set<String> _sent = {};

  void reportProbe(int tmdbId, String mediaType) =>
      _fire('probe', tmdbId, mediaType);

  void reportPlayback(int tmdbId, String mediaType) =>
      _fire('playback', tmdbId, mediaType);

  void _fire(String kind, int tmdbId, String mediaType) {
    final key = '$kind:$tmdbId:$mediaType';
    if (!_sent.add(key)) return; // already sent this session
    // Fire-and-forget: swallow errors, never await at the call site.
    () async {
      try {
        await _api.report(tmdbId: tmdbId, mediaType: mediaType, kind: kind);
      } catch (e) {
        _log.warn('availability report failed ($key): $e');
        _sent.remove(key); // allow a retry next time
      }
    }();
  }
}

/// Process-lived reporter (the dedup set should survive across page
/// navigations within a session). Null-safe: if the API isn't ready yet,
/// reports are silently dropped (best-effort signal).
final availabilityReporterProvider = Provider<AvailabilityReporter?>((ref) {
  final apiAsync = ref.watch(availabilityApiProvider);
  return apiAsync.maybeWhen(
    data: AvailabilityReporter.new,
    orElse: () => null,
  );
});
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `flutter test test/state/availability_reporter_test.dart --no-pub`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add lib/state/availability_reporter.dart test/state/availability_reporter_test.dart
git commit -m "state(availability): AvailabilityReporter fire-and-forget + dedup"
```

---

### Task 16: Wire probe + playback hooks

**Files:**
- Modify: `lib/plugins/routing/router.dart` (the probe match point ~line 126)
- Modify: `lib/domain/play_title.dart` (`_registerAndUrl` ~line 72) + `lib/state/play_controller_provider.dart`
- Test: `test/domain/play_title_test.dart`

- [ ] **Step 1: Decide the wiring seam (read before coding)**

`ProviderRouter` and `PlayController` are constructed in `play_controller_provider.dart`. The reporter is a provider. To avoid threading riverpod into these plain classes, give each an optional callback:
- `ProviderRouter` gains `void Function(int tmdbId, String mediaType)? onProbeMatch;`
- `PlayController` gains `void Function(int tmdbId, String mediaType)? onPlaybackResolved;`
The provider wires both to the reporter. This keeps the classes testable without riverpod.

- [ ] **Step 2: Write the failing test**

Add to `test/domain/play_title_test.dart`:

```dart
test('startMovie fires onPlaybackResolved with tmdbId+mediaType', () async {
  final calls = <(int, String)>[];
  // build a PlayController with a stub router that resolves a bundle,
  // passing onPlaybackResolved: (id, mt) => calls.add((id, mt))
  // ...
  await controller.startMovie(tmdbId: 42);
  expect(calls, [(42, 'movie')]);
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `flutter test test/domain/play_title_test.dart --no-pub`
Expected: FAIL (`onPlaybackResolved` param doesn't exist).

- [ ] **Step 4: Add the callbacks**

In `lib/domain/play_title.dart`, add the field to `PlayController`:

```dart
  final void Function(int tmdbId, String mediaType)? onPlaybackResolved;
```
(Add it to the constructor as an optional named param.) In `_registerAndUrl`, right before `return`, call it:

```dart
    onPlaybackResolved?.call(tmdbId, mediaType);
```

In `lib/plugins/routing/router.dart`, add the field to `ProviderRouter`:

```dart
  final void Function(int tmdbId, String mediaType)? onProbeMatch;
```
(Constructor optional named param.) The probe match point already sets `found = true` when `_resolveEntry` returns non-null — but `probeAvailability` takes a `TitleHint` (title/year), not a tmdbId. The tmdbId is known by the *caller* of `probeAvailability` (the `availabilityProvider` family key has it). Simplest correct wiring: fire `onProbeMatch` from `availabilityProvider` in `lib/state/availability_provider.dart` instead — when the probe returns `true`, report it there (the key carries tmdbId + mediaType). So:
  - Do NOT add `onProbeMatch` to `ProviderRouter`.
  - Instead, in `lib/state/availability_provider.dart`, after the probe resolves `true`, call `ref.read(availabilityReporterProvider)?.reportProbe(key.tmdbId, key.mediaType)`.

Keep only the `onPlaybackResolved` callback on `PlayController` (playback path doesn't go through a riverpod provider with the id handy at the success point).

- [ ] **Step 5: Wire both in the provider**

In `lib/state/play_controller_provider.dart`, pass the playback callback:

```dart
  final reporter = ref.read(availabilityReporterProvider);
  // ...
  return PlayController(
    // ...existing args...
    onPlaybackResolved: (id, mt) => reporter?.reportPlayback(id, mt),
  );
```

In `lib/state/availability_provider.dart`, add the probe report after a true result:

```dart
  final available = await controller.router.probeAvailability(/* ...existing... */);
  if (available) {
    ref.read(availabilityReporterProvider)?.reportProbe(key.tmdbId, key.mediaType);
  }
  return available;
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `flutter test test/domain/play_title_test.dart --no-pub`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add lib/domain/play_title.dart lib/plugins/routing/router.dart lib/state/play_controller_provider.dart lib/state/availability_provider.dart test/domain/play_title_test.dart
git commit -m "client: report probe (availabilityProvider) + playback (PlayController) crowd events"
```

---

### Task 17: Phase 2 verification

- [ ] **Step 1: Backend full suite**

Run: `cd /Users/alfanowski/Desktop/Projects/Streamload && venv/bin/python -m pytest -q`
Expected: all pass except the known pre-existing `test_get_catalog_item_404`.

- [ ] **Step 2: Client analyze + test**

Run: `cd /Users/alfanowski/Desktop/Projects/Streamload-Client && flutter analyze --no-pub && flutter test --no-pub`
Expected: analyze clean of errors; tests green (≥ 429 + the new ones).

- [ ] **Step 3: Manual smoke (operator)**

Start backend + client. Watch a title fully (triggers a `playback` report). Re-open Home → that title (if it appears in a row) should rank higher. Check `psql ... -c "SELECT * FROM title_availability;"` shows incremented counters. Verify playback is NOT broken when the backend is stopped mid-session (fire-and-forget swallows the failed report).

---

## Self-Review Notes

- **Spec coverage:** heuristic scorer (Task 2) ✓; stable bucket sort (Task 3) ✓; anime JP fix (Tasks 4, 7) ✓; row wiring (Task 5) ✓; crowd table (Task 10) ✓; report endpoint (Task 12) ✓; both-weighted events (Tasks 9, 11) ✓; client hooks probe+playback (Task 16) ✓; ranking NOT applied to search/lista/continua (Task 5 only touches `/rows/*`) ✓; soft-priority/no-drop (Task 3 `test_rank_preserves_all_items_no_drops`) ✓.
- **Wire word mapping:** client/endpoint use `kind="playback"`; the DAO uses `kind="play"`. The route maps `playback→play` (Task 12). Consistent throughout.
- **Phase 1/2 seam:** `rank_by_playability` ships in Phase 1 with a `crowd_score` placeholder (Task 3) replaced by the real one in Task 9 — so Phase 1 is independently shippable and green.
- **Type consistency:** `CrowdCounts(probe_count, play_count)` used identically in Tasks 9, 11, 13. `GenreRowKey.origin` (default `'western'`) used in Tasks 6, 7. `discover_by_genre(origin=...)` in Tasks 4, 5.
