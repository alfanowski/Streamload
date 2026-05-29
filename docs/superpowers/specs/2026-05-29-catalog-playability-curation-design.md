# Catalog Playability Curation — Design

**Date:** 2026-05-29
**Scope:** Sub-plan 9 (intelligent catalog curation)
**Status:** Approved — ready for implementation plan

## Goal

Rank catalog rows so titles that are actually playable by the Italian plugins
(sc / au / rai) float to the top, and fix the Anime rows surfacing Western
cartoons instead of Japanese anime. Soft-priority: nothing is hidden — the
existing "Al momento non disponibile" button still handles the residual
unplayable cases on the title page.

## Problem

The Home and browse rows proxy TMDB and render whatever TMDB returns. Half of
those titles aren't reproducible by the plugins (obscure regional content,
titles the scrapers don't index). Knowledge of "is this playable" lives in
the **client plugins** (JS scrapers in the sandbox); the backend has no
plugins and — under legal posture B (yt-dlp style) — must never run scrapers.
So curation cannot probe playability on the backend. We approximate it with a
heuristic (cold-start prior) refined by a crowd-sourced usage signal.

## Decisions taken (brainstorm)

1. **Soft priority**, not hard filter: show all TMDB results, sort playable
   first. No empty rows. Residual misses handled by the existing title-page
   unavailable state.
2. **Two-layer signal**: heuristic now + crowd-sourced layered on top.
3. **Crowd events both weighted**: `probe` (weak — found in plugin search) and
   `playback` (strong — stream resolved and player started).
4. **Backend-centric ranking**: the backend ranks rows before serving; the
   client renders pre-ordered rows. No plugin calls in the ranking path, no
   extra client round-trips.

## Architecture

```
client GET /api/catalog/rows/X
   → backend fetches TMDB results (existing)
   → backend loads crowd availability map for those tmdb_ids (one indexed query)
   → rank_by_playability(items, crowd_map)  ← heuristic + crowd, stable bucket sort
   → serve ordered list
```

The client stays dumb: it receives already-ordered rows. The crowd table lives
on the backend (where it's aggregated anyway). Ranking is applied at a single
point — the row endpoints — and NOT to search, "La mia lista", or "Continua a
guardare" (those have intrinsic order that must be preserved).

### Stable bucket sort (not a pure sort)

A pure sort by playability would destroy the row's intrinsic meaning (a
"Tendenze" row would no longer be in trending order). Instead, partition into
two buckets, each preserving the original TMDB order:

- **Bucket A** — `playability_score >= THRESHOLD` (playable-likely), in TMDB order
- **Bucket B** — below threshold, in TMDB order

Concatenate A ++ B. Playable titles rise to the top while the intrinsic
ordering within each bucket is untouched.

`THRESHOLD` is a tunable constant in `playability.py` (start at the heuristic
midpoint; document the value).

## Component 1 — Heuristic scorer (Phase 1)

Pure function in `streamload/catalog/playability.py`:

```python
def heuristic_score(item: TmdbItem, *, is_anime_row: bool = False) -> float:
    """0..100 prior probability that the IT plugins can play this title.
    Uses ONLY fields already present in the TMDB discover/trending payload —
    no extra round-trips."""
```

Signals (weights are starting values, tuned in tests, documented in code):

| Signal | Weight | Rationale |
|---|---|---|
| Origin Western (movie/tv) OR JP (anime row) | 40 | plugins cover mainstream Western + JP anime |
| `original_language` ∈ {it, en} | 20 | sc dubs EN/US heavily; rai is IT |
| `vote_count` (log-scaled, capped) | 20 | plugins carry the mainstream, not the obscure |
| `popularity` (normalized, capped) | 12 | same |
| recency (released within ~3 years) | 8 | slightly likelier to be on the providers |

For anime rows the origin check flips: JP origin scores the 40, Western scores 0.
For non-anime rows: Western origin scores the 40, non-Western (incl. JP) scores 0
— matching the existing `_WESTERN_COUNTRIES` discover filter.

`TmdbItem` already carries `original_title`, `year`, `rating`. The discover/
trending raw payload also has `original_language`, `origin_country`/`origin`,
`vote_count`, `popularity`, `release_date`/`first_air_date`. The scorer needs a
few fields not currently on `TmdbItem` — extend the dataclass with
`original_language`, `origin_country: list[str]`, `vote_count`, `popularity`
(all optional, populated from the raw payload in `_parse_movie`/`_parse_tv`).

## Component 2 — Crowd-sourced availability (Phase 2)

### Table `title_availability`

```
tmdb_id      int        \  composite PK
media_type   text       /  ('movie' | 'tv')
probe_count  int        default 0
play_count   int        default 0
last_seen_at timestamptz
```

Alembic migration. No provider breakdown for v1 (YAGNI — we need "is it
playable", not "on which provider"; a provider column can be added later).

### Endpoint `POST /api/availability/report`

Body: `{tmdb_id: int, media_type: "movie"|"tv", kind: "probe"|"playback"}`.
Auth required (reuse `CurrentUser`). UPSERT: insert row or increment the
matching counter (`probe_count` or `play_count`) and bump `last_seen_at`.
Returns 204. Validates `media_type` + `kind`.

### Client report hooks (fire-and-forget)

- **probe** — in `ProviderRouter.probeAvailability`, after a plugin returns a
  non-null match, fire a `probe` report for the (tmdbId, mediaType). Weak signal.
- **playback** — in `PlayController`, after `getStreams` returns a valid
  manifest AND playback starts, fire a `playback` report. Strong signal.

Both via a new `AvailabilityReporter` (a thin client over the endpoint).
Fire-and-forget: wrapped so a failed/slow report never blocks the UI or breaks
playback. Deduped per session (don't spam the same title repeatedly) via an
in-memory set on the reporter.

### Aggregation in ranking

```
crowd_score = play_count * 3 + probe_count * 1     # play strongly outweighs probe
```

Normalized (log-scaled + capped to ~30 points) and ADDED to the heuristic
score before bucketing. A title someone actually watched beats any heuristic.
Cold start (both counts 0) → crowd_score 0 → pure heuristic, no regression.

The row endpoint loads the crowd map with one query:
`SELECT tmdb_id, media_type, probe_count, play_count FROM title_availability
WHERE (tmdb_id, media_type) IN (...the row's ids...)`.

## Component 3 — Anime origin fix (Phase 1)

The Anime rows call `/rows/by-genre genre=16`, which runs `discover_by_genre`
with the `_WESTERN_COUNTRIES` origin filter → Western cartoons. Fix:

- Add an optional `origin` query param to `/rows/by-genre` (values: `western`
  default, `jp`). When `origin=jp`, the TMDB call uses `with_origin_country=JP`
  instead of the Western list (mirrors the existing `discover_anime`).
- The client anime rows (`_buildAnimeRows`) pass `origin=jp` on their genre
  queries.
- The heuristic scorer is told `is_anime_row=True` for these rows so JP origin
  scores the origin points.

## Ranking application points

`rank_by_playability(items, crowd_map, *, is_anime_row)` is applied in:

- `/rows/trending`
- `/rows/new-releases`
- `/rows/by-genre`
- `/rows/top-rated`

NOT applied in: `/api/search`, `/api/person/{id}/credits`, the client-side
"La mia lista" / "Continua a guardare" rows (intrinsic order matters there).

## Phasing

- **Phase 1 — Heuristic + anime fix + bucket sort.** Ships immediate value.
  No new table, no client changes beyond the anime rows passing `origin=jp`.
  - Extend `TmdbItem` with the scorer fields + populate them
  - `playability.py`: `heuristic_score` + `rank_by_playability` (crowd_map
    optional/empty in this phase)
  - Wire `rank_by_playability` into the four row endpoints
  - `origin=jp` param + client anime rows use it
- **Phase 2 — Crowd-sourced layer.** Stacks on top.
  - `title_availability` table + migration
  - `POST /api/availability/report`
  - `AvailabilityReporter` client + probe/playback hooks
  - Row endpoints load the crowd map and pass it to `rank_by_playability`

## Testing

**Phase 1**
- Unit `heuristic_score`: Western movie > Eastern movie; IT/EN original lang
  boost; popular > obscure; anime row flips origin (JP scores, Western doesn't);
  fields-missing degrades gracefully (no crash, lower score).
- Unit `rank_by_playability`: bucket A preserves intra-bucket TMDB order;
  bucket B follows; empty crowd_map = pure heuristic.
- API: each `/rows/*` returns items reordered playable-first; anime row with
  `origin=jp` returns JP-origin items.
- Client: anime rows request `origin=jp`.

**Phase 2**
- Unit UPSERT: probe then playback on the same title accumulates both counters.
- Unit aggregation: `crowd_score` weights play 3× probe; cold start = heuristic only.
- API: `/api/availability/report` increments the right counter, validates
  media_type/kind, 204 on success, auth required.
- API: `/rows/*` with a seeded crowd map ranks a played title above a
  heuristically-stronger but never-played one.
- Client: `AvailabilityReporter` fires probe on match + playback on success;
  a failing report does NOT block playback or the probe result; per-session dedup.

## Non-goals

- Hard filtering (hiding unplayable titles) — explicitly soft-priority
- Per-provider availability breakdown — single playable signal for v1
- Backend running the scrapers — forbidden by legal posture B
- Re-ranking search / La mia lista / Continua a guardare
- Probing every row title client-side (the rejected "probe + reorder" option)
- A machine-learned ranker — the heuristic + crowd counters are enough at this scale
