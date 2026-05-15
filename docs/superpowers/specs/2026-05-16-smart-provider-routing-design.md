# Smart Provider Routing — Design

**Date:** 2026-05-16
**Scope:** Sub-plan 7 (multi-provider routing, post-MVP playback)
**Status:** Approved — ready for implementation plan

## Goal

Expand the Streamload v3 client from a single-provider (sc) to a multi-provider model where `PlayController` fans out to multiple plugins at play time, scores their streams by quality, and serves the best one. Add two new providers verified live (animeunity, raiplay) alongside the existing sc.

## Decisions taken

1. **Provider scope (this round):** `sc` + `animeunity` + `raiplay`.
   - **Dropped:** `mediasetinfinity` (explicit no-scraping ToS + Widevine DRM on the premium catalog), `guardaserie` (no live domain found across 19 TLD candidates).
2. **Fan-out point:** play time only. TMDB remains the catalog/search backbone; plugins are consulted only when the user taps Guarda.
3. **Strategy:** quality scoring. Fan-out parallel across all plugins whose capabilities cover the request's `mediaType`; wait up to a deadline (5s) for `getStreams` to resolve; pick the highest-scored bundle.
4. **Healthcheck:** in-memory failure counter per plugin. If a plugin's failure rate exceeds 50% over the last 1h sliding window, skip it for the next play request (re-enable on next mount or after 10 min cool-down).
5. **Cache:** per `(tmdbId, season?, episode?)`, remember which plugin produced a valid bundle. 10-min TTL. On re-watch within window, try the cached plugin first; on its failure fall back to full fan-out.

## Provider verification (probes run 2026-05-16)

| Provider | Base URL | Status | API style |
|---|---|---|---|
| `sc` | `streamingcommunityz.band` | live (v1.0.2) | Inertia + Laravel paginate |
| `animeunity` | `animeunity.so` | live | CSRF POST + REST (`/livesearch`, `/archivio/get-animes`, `/info_api/{id}/`) |
| `raiplay` | `www.raiplay.it` | live | Atomatic msearch JSON POST + program JSON descriptors |
| `mediasetinfinity` | — | **dropped** | ToS prohibits scraping; Widevine DRM blocks premium |
| `guardaserie` | — | **dropped** | No live mirror found |

## Quality scoring rubric (initial; revisable)

Each `StreamBundle` is scored from 0 to 100 by summing:

- **Resolution** (max 40): 2160p=40, 1080p=30, 720p=20, 480p=10, else 0
- **Italian audio track present** (20): yes=20, no=0
- **Italian subtitles present** (10): yes=10, no=0
- **Codec**: H.264/AAC (15), HEVC/AAC (10), AV1 (5)
- **No DRM required** (15): no=15, yes=0
- **Provider weight** (multiplicative, 0.8–1.2): from per-plugin reliability stats

The scorer is a pure function in `lib/plugins/routing/quality.dart` for testability.

## Architecture changes

### New files

```
lib/plugins/routing/
├── router.dart           orchestrates fan-out + scoring + cache
├── quality.dart          pure scoring function
├── health.dart           in-memory failure counter, sliding window
└── cache.dart            in-memory tmdbId→plugin LRU (10-min TTL)
```

### Modified files

- `lib/domain/play_title.dart` — `PlayController.resolveStreams` calls `Router.bestBundle(target)` instead of single `pluginFor`
- `lib/state/play_controller_provider.dart` — wires `Router` (constructed once per session)
- `test/plugins/routing/*.dart` — unit tests for quality scoring, health window, cache

### Plugin files (in streamload-plugins repo)

- `plugins/animeunity.js` — new, ~400-500 lines. Capabilities: `tv:anime`, `movie:anime`
- `plugins/raiplay.js` — new, ~350-400 lines. Capabilities: `tv`, `movie`
- `registry.json` — add the two entries, with sha256 + version

## Non-goals (this round)

- Netflix-style UX (home rows, hero carousel, title page redesign) — sub-plan 8
- DRM/Widevine support — separate effort
- Per-user provider preferences — defer until we have 3+ active and see real usage
- Streaming quality probe (`pickQuality` from v2 streaming/) — not needed for routing decisions, can be added later
- Mediaset reverse-engineering — abandoned
- Guardaserie live domain — defer until operator finds one

## Test plan

- Unit: quality scorer (table-driven cases per provider weight + resolution + audio combos)
- Unit: health counter (failure rate computation across sliding window)
- Unit: cache (eviction on TTL expiry, LRU on capacity)
- Integration: `Router.bestBundle` with three fake plugins (one returns 1080p, one 720p, one throws) → expect 1080p winner + thrown one's health degraded
- E2E (manual): with all 3 real plugins, search a popular movie + a popular anime + a popular Italian series; verify the right provider wins for each
