# Streamload v3 — Re-platforming Design

**Status:** Approved (brainstorming phase complete, awaiting user spec review).
**Author:** alfanowski + design partner.
**Date:** 2026-05-09.
**Successor to:** v0.2.x (Python FastAPI backend + SvelteKit web frontend).

---

## 1. Goals

Re-platform Streamload as a **native desktop application** that does all upstream scraping + media playback **locally on the user's device**, leaving the operator's server with only legal-by-construction responsibilities (auth, TMDB metadata mirror, user-state sync).

### 1.1 Functional goals (parity with v2)

- Auth (WebAuthn passkey + email/password fallback).
- Browse curated TMDB collections (popular movies, popular tv, trending day, anime season, top-rated, etc.).
- Search any TMDB title with lazy-ingest of metadata.
- Title detail with overview, cast, ratings.
- TV series with seasons + episodes + per-episode resume.
- HLS playback with quality auto-select, AES-128 decryption, multi-audio, multi-server fallback.
- Favorites, watchlist, continue-watching synced cross-device.
- User settings (preferred audio/subs language, quality cap, autoplay-next, theme, locale) synced cross-device.
- "Next up" smart resume (server computes next episode after a complete).
- Multi-device awareness (badge "active on iPhone 12m ago").

### 1.2 Non-functional goals

- **Legal posture (B / "yt-dlp posture")**: the published binary and the server contain zero references to upstream pirated services. Plugins are distributed out-of-band via a private GitHub repo. The operator's identity remains attached to the public app and the server, but never to the plugin pack.
- **Enterprise-grade desktop UX**: native compiled, hardware-accelerated player, sub-100ms response on every interaction, auto-update Sparkle-class.
- **Single codebase** across Mac/Win/Linux today, mobile (iOS/Android) post-MVP.
- **Offline-first**: every user action persists locally first, then syncs.
- **Zero PII leakage**: the backend never knows which plugin or which upstream URL was used for any playback.

### 1.3 Explicit non-goals (deferred to post-MVP)

- Mobile (iOS/Android) clients.
- Apple Developer Program ($99/yr) + code signing + notarization.
- Admin web portal (separate spec/plan; backend will collect telemetry now so the future portal has data).
- Plex/Jellyfin/Emby integration.
- Cast / AirPlay (present in v2, deferred).
- Skip-intro automatic detection (present in v2, deferred to post-parity hardening).

---

## 2. Three invariants (legal posture, non-negotiable)

These three rules MUST hold for every change, forever:

1. **The backend never talks to the 13 upstream scraping services.** No reverse-lookup, no HLS proxy, no source URL persistence. The proof is structural: `streamload/services/`, `streamload/streaming/`, and the `catalog_sources` table do not exist server-side.
2. **The published binary contains zero references to scraping plugins.** If someone unzips the `.app`, no plugin code, no service short_names, no upstream domains are findable. The app is a generic "media engine + plugin runtime" branded as a personal media library.
3. **The only link between the public app and the private plugins is a per-user GitHub PAT** that the user pastes once during onboarding. The PAT lives in the OS keychain. The server never sees it. The public repo never references it.

Any architectural decision that violates one of these is rejected without further debate.

---

## 3. System architecture

```
┌─────────────────────────────────────────┐
│ Client Flutter (Mac MVP, then Win/Linux,│  ← scraping + playback ENTIRELY local
│                 then iOS/Android)       │
├─────────────────────────────────────────┤
│ • Flutter UI (parity with v2 SvelteKit) │
│ • drift + SQLite (catalog cache, sources│
│   radioattive, outbox)                  │
│ • flutter_js + QuickJS (plugin sandbox) │
│ • shelf (Dart) HLS proxy on 127.0.0.1   │
│ • media_kit (libmpv) player             │
│ • auto_updater (Sparkle/winsparkle)     │
└─────────┬───────────────────┬───────────┘
          │ HTTPS             │ HTTPS
          │ session cookie    │ Bearer PAT
          ▼                   ▼
┌───────────────────────┐  ┌──────────────────────┐
│ Backend (operator VPS)│  │ GitHub PRIVATE repo  │
├───────────────────────┤  │ streamload-plugins   │
│ FastAPI + Granian +   │  ├──────────────────────┤
│ Postgres (~40% of v2  │  │ registry.json        │
│ codebase, ridotto)    │  │ plugins/*.js         │
│                       │  │                      │
│ • Auth (WebAuthn +    │  │ One PAT per end-user,│
│   sessions)           │  │ scope=repo:read      │
│ • TMDB metadata mirror│  │                      │
│ • User-data sync      │  │ Owner pushes via PR  │
│ • Telemetry events    │  │ Client reads via API │
│                       │  │                      │
│ ZERO scraping logic   │  │ NEVER linked from    │
│ ZERO source URLs      │  │ public app or server │
└───────────────────────┘  └──────────────────────┘
```

---

## 4. Client (Flutter) internal architecture

Layered, communication via typed interfaces:

```
presentation/         Flutter widgets, riverpod state
  ├ pages/            home, search, title, watch, profile, library
  ├ widgets/          PosterCard, EpisodeList, Row, NavBar, …
  └ theme/            "Cinematic Editorial" port from v2 app.css

domain/               Pure use-cases (no Flutter, no IO)
  ├ play_title.dart
  ├ ingest_title.dart
  ├ resolve_sources.dart
  ├ sync_user_data.dart
  └ next_up.dart

data/
  ├ remote/
  │   └ ApiClient     Backend HTTP client (cookie auth, retry, idempotency)
  ├ local/
  │   ├ db.dart       drift connection + migrations
  │   ├ daos/         CatalogDao, EpisodesDao, SourcesDao, OutboxDao,
  │   │               FavoritesDao, WatchlistDao, ProgressDao, …
  │   └ schema/       drift table definitions
  └ secure/           flutter_secure_storage adapter (session, PAT)

plugins/              JS plugin runtime
  ├ runtime.dart      flutter_js engine wrapper, lifecycle
  ├ host_api.dart     http / html / crypto / log / storage / url
  ├ registry.dart     loaded plugin list, capabilities index
  └ pack_loader.dart  download from GitHub, sha256 verify, mount

player/
  ├ proxy.dart        shelf HTTP server, master/variant/key/seg routes
  ├ rewriter.dart     port of v2 m3u8_rewrite (strip subs, fix key URI)
  ├ session.dart      PlaybackSession registry (in-memory)
  └ engine.dart       media_kit Player wrapper

updater/
  ├ app_updater.dart  auto_updater package wrapper
  └ plugin_updater.dart  poll registry.json, diff, fetch, swap

settings/             User preferences (synced + cached locally)

infra/
  ├ logging.dart      structured logging, redact PAT/tokens
  ├ http.dart         dio singleton with cookie jar
  └ events.dart       telemetry batching (queue + flush)
```

**State management**: `riverpod` (ProviderContainer + AsyncValue), test-friendly, replaces v2 SvelteKit stores 1:1.

**Routing**: `go_router`, declarative, deep-link friendly. Routes mirror v2 URL structure: `/`, `/library/movies`, `/title/:tmdb_id?media_type=`, `/watch/:tmdb_id?media_type=&season=&episode=`, `/search`, `/profile`, etc.

---

## 5. Backend (reduced shape)

### 5.1 What survives

```
streamload/
├ api/routes/
│   ├ auth.py          POST /auth/register, /login, /logout
│   ├ passkey.py       /passkey/register/{begin,complete},
│   │                  /passkey/login/{begin,complete}
│   ├ me.py            GET /me
│   ├ email.py         POST /auth/verify-email, /reset-password
│   ├ catalog.py       GET /catalog/{tmdb_id}?media_type=
│   │                  ↑ lazy-ingest TMDB only, sources=[] always
│   ├ collections.py   GET /collections, /collections/{id}
│   ├ episodes.py      GET /title/{tmdb_id}/episodes
│   ├ search.py        GET /search?q=…  (TMDB live)
│   ├ progress.py      POST /progress, GET /progress/continue-watching
│   ├ favorites.py     /favorites/{id}?media_type=
│   ├ watchlist.py     /watchlist/{id}?media_type=
│   ├ library.py       GET /library?media_type=&page=
│   ├ intro.py         GET /intro/{tmdb_id}/s{season}
│   ├ settings.py      GET/PUT /settings
│   ├ next_up.py       NEW. GET /next-up/{tmdb_id}?season=&episode=
│   ├ events.py        NEW. POST /events  (batch telemetry write)
│   └ admin.py         users CRUD, stats, top-watched, events queries
└ catalog/
    ├ tmdb.py
    ├ collections.py
    ├ ingest.py        ingest_collection / ingest_single_title
    │                  ↑ no _resolve_sources_for_item, no services arg
    ├ service.py       CatalogService (read API)
    └ worker.py        refresh_due_collections (TMDB only)
```

### 5.2 What dies

- All of `streamload/services/`.
- All of `streamload/streaming/`.
- All of `streamload/utils/domain_resolver/`.
- Routes `/api/play/*`, `/stream/*`, `/api/admin/catalog/refresh/*` (the refresh worker stays, the on-demand admin trigger goes — it implied scraping).
- `catalog_sources` table.
- `last_source` column on `watch_progress`.
- The `quality_max_height` write-back from the stream proxy (never invoked anymore).

### 5.3 Schema additions

Migration `0008_v3_remodel.py`:

- DROP TABLE `catalog_sources` (CASCADE handles its FKs).
- ALTER TABLE `watch_progress` DROP COLUMN `last_source`.
- CREATE TABLE `user_settings(user_id PK FK, audio_pref_lang, subs_pref_lang, quality_cap_height, autoplay_next_episode, skip_intro, theme, locale, updated_at)`.
- CREATE TABLE `watch_history(user_id, tmdb_id, media_type, season_number, episode_number, completed_at, PK(user_id, tmdb_id, media_type, season_number, episode_number, completed_at), FK(tmdb_id, media_type) → catalog_items)`.
- CREATE TABLE `search_history(id BIGSERIAL PK, user_id, query_text TEXT, query_hash CHAR(64), executed_at)`.
- CREATE TABLE `events(id BIGSERIAL PK, user_id, event_type TEXT, payload JSONB, ip INET, user_agent TEXT, app_version TEXT, occurred_at, INDEX(user_id, occurred_at), INDEX(event_type, occurred_at))`.

### 5.4 Telemetry events captured (level B)

| event_type | payload | Triggered by |
|---|---|---|
| `auth.login_success` | `{}` | /auth/login on success |
| `auth.login_failed` | `{ reason }` | /auth/login on 401 |
| `auth.logout` | `{}` | /auth/logout |
| `auth.passkey_register` | `{}` | /passkey/register/complete |
| `catalog.view` | `{ tmdb_id, media_type }` | client posts on title open |
| `search.run` | `{ query_hash, result_count }` | client posts after search |
| `play.start` | `{ tmdb_id, media_type, season?, episode? }` | client posts on player load. NO plugin/source name. |
| `play.complete` | `{ tmdb_id, media_type, season?, episode?, position_at_end_seconds, duration_seconds }` | client posts on >90% watched. |
| `favorite.add` / `.remove` | `{ tmdb_id, media_type }` | server-side after mutation |
| `watchlist.add` / `.remove` | `{ tmdb_id, media_type }` | server-side after mutation |
| `app.start` | `{ app_version, os, locale }` | client posts on launch |
| `plugin_pack.installed` | `{ pack_version }` | client posts after install. NO plugin names. |
| `plugin_pack.updated` | `{ from_version, to_version }` | client posts after auto-update. NO plugin names. |

`ip` and `user_agent` are captured server-side from the request, **only** for events posted via authenticated requests. Retention policy: 90 days (admin portal will surface drop-off / DAU / cohorts).

### 5.5 GDPR posture

- Public ToS clause: "we collect usage events to operate and improve the service. You can request export or deletion of your data."
- `/me/data-export` and `/me/data-delete` endpoints (deferred to admin portal phase, not v3 client MVP).
- 10 known users, identifiable, with explicit consent at registration. Risk profile: low.

---

## 6. Plugin system

### 6.1 Repo layout (private GitHub)

```
streamload-plugins/
├ registry.json
└ plugins/
    ├ streamingcommunity.js
    ├ animeunity.js
    ├ animeworld.js
    ├ raiplay.js
    ├ mediasetinfinity.js
    ├ guardaserie.js
    ├ mostraguarda.js
    ├ discovery.js
    ├ dmax.js
    ├ realtime.js
    ├ tubitv.js
    ├ foodnetwork.js
    ├ nove.js
    ├ homegardentv.js
    └ crunchyroll.js
```

### 6.2 `registry.json` shape

```json
{
  "format_version": 1,
  "updated_at": "2026-05-09T20:00:00Z",
  "plugins": [
    {
      "short_name": "sc",
      "file": "plugins/streamingcommunity.js",
      "version": "1.0.5",
      "api_version": 1,
      "sha256": "abc…",
      "min_app_version": "0.3.0"
    }
  ]
}
```

The client compares `version` and `sha256` against its local copy and pulls only what changed.

### 6.3 Plugin file shape

```js
export const meta = {
  short_name: "sc",
  display_name: "StreamingCommunity",
  version: "1.0.5",
  api_version: 1,
  capabilities: ["movie", "tv", "tv:anime"],
};

export async function search(query) { /* … */ }
export async function getSeasons(entry) { /* … */ }
export async function getEpisodes(season) { /* … */ }
export async function getStreams(target) {
  return {
    manifest_url: "https://upstream/master.m3u8",
    headers: { Referer: "https://sc.foo/" },
    is_drm: false,
    drm_keys: null,
  };
}
```

### 6.4 Capabilities (closed enum)

```
movie               movie:anime           movie:kids        movie:documentary
tv                  tv:anime              tv:kids           tv:documentary
tv:reality          tv:news               tv:sport
```

The client uses capabilities to route home sections ("Anime" queries only `*:anime` plugins) and to skip plugins that can't satisfy a request. Capabilities outside this enum cause the plugin to be rejected with a warning in the log; expanding the set requires bumping `api_version`.

### 6.5 Sandbox host API

```ts
host.http.fetch(url, { method?, headers?, body?, cookies? })
   → { status, headers, body, cookies, finalUrl }
host.html.parse(text)        → cheerio-like DOM
host.crypto.aesDecrypt(buf, key, iv) | hmac | md5 | sha256 | base64
host.log.{debug,info,warn,error}(msg)
host.storage.{get,set,delete}(key)   namespaced to plugin:{short_name}:
host.url.absolute(maybeRelative, base)
host.json.{parse,stringify}
```

The sandbox has **no** `fs`, `process`, `eval`, no DB access, no other plugin's data, no backend access. `http.fetch` defaults: 10s timeout, 10MB max body, max 5 redirects. All requests route through the app's `dio` singleton (so user proxies/timeouts apply).

### 6.6 Onboarding flow (PAT install)

```
First-run wizard step 3:
  "To access content, paste the GitHub Personal Access Token your administrator gave you."
  [ ____________________________ ]
  [ Verify and install ]

Client:
  GET https://api.github.com/repos/{owner}/{repo}/contents/registry.json
  Authorization: Bearer ghp_…
  → 200 → save PAT in flutter_secure_storage
       fetch each plugins/*.js
       sha256 verify
       load in JS runtime
       mark pack as "installed at registry.updated_at"
  → 401 → "Invalid token"
```

The PAT is generated by the operator with `repo:read` scope on `streamload-plugins` only. One PAT per end-user, distributed out-of-band (Signal, in-person).

### 6.7 Update flow

```
On app start + every 30 minutes while app is open:
  1. GET registry.json
  2. Diff against local registry
  3. For each changed plugin: fetch, sha256 verify, swap in runtime atomically
  4. Log "plugin sc updated 1.0.5 → 1.0.6"
```

Silent by default. Optional toast "Plugin aggiornati" can be enabled in settings. Atomic swap: if sha256 fails, the old plugin remains active and the new one is discarded.

### 6.8 Disable / enable

Settings → Plugins lists installed plugins with toggle on/off. Disabled plugins are kept on disk but not registered with the runtime.

---

## 7. HLS playback pipeline

```
User clicks "Watch S03E07"
  ↓
domain/play_title:
  1. Read sources from local SQLite for (tmdb_id, media_type)
  2. If empty: domain/resolve_sources kicks in → for each plugin
     matching capabilities, call plugin.search/getSeasons/getEpisodes
     in sandbox, persist results to SQLite
  3. Local ranker (quality, latency, reliability, audio/subs match) →
     ordered candidate list
  4. For each candidate until one succeeds:
     a. plugin.getStreams(target) in sandbox
     b. Receive { manifest_url, headers, is_drm, drm_keys }
     c. Create PlaybackSession in memory, register in local proxy
     d. If is_drm, decrypt in-memory using pointycastle
     e. Return master_url = http://127.0.0.1:47821/master/{sid}.m3u8
  5. media_kit Player.open(Media(master_url, httpHeaders={...}))
  6. Player events → 5-second-throttled progress poller →
     POST /api/progress (no last_source)
  7. On >90% played: client emits play.complete telemetry +
     server inserts into watch_history.
```

**Local proxy** (`shelf` Dart):
- Bind 127.0.0.1, ephemeral port (system-assigned).
- Routes: `/master/{sid}.m3u8`, `/variant/{sid}/{rendition}`, `/key/{sid}/{rendition}`, `/seg/{sid}/{rendition}/{n}.ts`.
- Same rewrite logic as v2 backend `m3u8_rewrite.py` ported to Dart: strip `EXT-X-MEDIA TYPE=SUBTITLES`, rewrite `EXT-X-KEY URI=` to local proxy URL, rewrite STREAM-INF and EXT-X-MEDIA URIs to local variant paths.
- Segment cache on disk (LRU 30 GB) via `path_provider`.
- RAM ring buffer for the next 30 segments to mask scrubbing latency.

**Subtitles**: subtitle support is deferred to post-parity (v2 also strips them today). When added, they will be served as separate WebVTT tracks via `<track>` semantics, NOT through HLS multi-rendition playlists.

---

## 8. Sync strategy & offline-first

### 8.1 What syncs and when

| Mutation | When pushed to server | When pulled from server |
|---|---|---|
| `favorites.add/remove` | Immediately, exp-backoff retry on failure | Pull all on app start |
| `watchlist.add/remove` | Immediately, exp-backoff retry on failure | Pull all on app start |
| `watch_progress` | Throttled 5s while playing, flushed on pause/seek/close | Pull all on app start + on title open |
| `user_settings` | Immediately on change | Pull on app start |
| `events` (telemetry) | Batch flush every 30s or 50 events (whichever first) | Never (write-only from client) |

### 8.2 Outbox

All client mutations write **first** to local DB (drift table `outbox`) within the user's transaction. A background isolate drains the outbox to the server, with exp-backoff. On 4xx responses (e.g. 409 conflict), the row is dropped and an event logged. On 5xx or network errors, retried up to 24h then surfaced as a settings-page warning.

### 8.3 Conflict resolution

- `watch_progress`: last-write-wins, server timestamp canonical. The client's local row is overwritten by the server's row when its `updated_at` is newer.
- `favorites` / `watchlist`: set semantics — "add" is idempotent, "remove" is idempotent. No conflicts.
- `user_settings`: last-write-wins on `updated_at`. The client never merges fields; it accepts the server's row wholesale.

### 8.4 Offline UX

The user can browse all cached titles, scroll through the home, mark favorites, watch already-resolved sources (cache hits play offline) — even with no network. Sync resumes when the network returns. Login is the only action that hard-requires the network (no local password verification).

---

## 9. Local persistence

### 9.1 Stack

- **drift** (typed SQLite ORM for Dart, equivalent to SQLAlchemy) for all relational state.
- **flutter_secure_storage** for tokens (session cookie, GitHub PAT).
- **shared_preferences** for trivial flat preferences (last sync timestamp, runtime locale guess).

### 9.2 Schema (drift)

Mirror of relevant backend tables + local-only:

- `catalog_items(tmdb_id, media_type, …)` — cached TMDB metadata.
- `tv_episodes(tmdb_id, media_type, season_number, episode_number, …)` — cached.
- `catalog_sources(tmdb_id, media_type, plugin_short_name, service_url, service_media_id, audio_langs, subs_langs, success_count, failure_count, last_verified_at)` — **LOCAL ONLY, never synced.**
- `favorites(tmdb_id, media_type, added_at)` — local mirror, synced.
- `watchlist(tmdb_id, media_type, added_at)` — local mirror, synced.
- `watch_progress(tmdb_id, media_type, season_number, episode_number, position_seconds, duration_seconds, completed, updated_at)` — local mirror, synced (no `last_source`).
- `user_settings(...single row...)` — local mirror, synced.
- `outbox(id, kind, payload_jsonb, created_at, attempts, next_attempt_at)` — pending sync.
- `installed_plugins(short_name, version, sha256, file_path, enabled, installed_at)`.
- `plugin_kv(plugin_short_name, key, value)` — backing store for `host.storage`.

### 9.3 Migrations

drift generates schema migrations from Dart annotations. Versioned under `lib/data/local/migrations/`. The first DB version ships with the v3 release; subsequent migrations are linear.

### 9.4 Footprint

After heavy use estimated at <200 MB total (catalog + sources + cache index + outbox). Segment cache on disk is separate (LRU 30 GB capped, configurable).

---

## 10. Auto-update flows

### 10.1 App update (Flow 1)

- **Source**: GitHub Releases on the public `Streamload-Client` repo (NEW repo for the v3 client, separate from v2 `Streamload-Web`).
- **Channel**: appcast.xml hosted on GitHub Pages (`alfanowski.github.io/Streamload-Client/appcast.xml`).
- **Library**: `auto_updater` Flutter package (Sparkle on Mac, WinSparkle on Win, custom on Linux).
- **Signature**: EdDSA signature on the zip embedded in appcast.xml. App ships the public key embedded; verifies before install.
- **Cadence**: check on launch + every 6 hours.
- **UX**: when update available, prompt "Aggiorna ora / Più tardi". On confirm: extract, atomic replace, relaunch.
- **Code signing**: skipped for MVP (Apple Developer not enrolled). Adding it later is a 1-day GHA pipeline change (apple-actions/import-codesign-certs + Apple notarytool).

### 10.2 Plugin update (Flow 2)

- **Source**: private `streamload-plugins` GitHub repo, raw API.
- **Auth**: per-user PAT in keychain.
- **Cadence**: check on launch + every 30 minutes while app is open.
- **UX**: silent by default. Optional "Plugin aggiornati" toast in settings.
- **Atomicity**: registry.json fetched first; per-plugin sha256 verified; mounted in JS runtime atomically. On any verification failure the new plugin is rejected and the old continues serving.

---

## 11. First-run onboarding

Three-screen wizard, skippable steps once their state is satisfied:

```
1. Welcome
   "Benvenuto in Streamload. Accedi o registrati."
   [ Accedi ] [ Crea account ]

2. Login
   email/username + password
   - or -
   "Accedi con Touch ID" (visible only if a passkey is registered on this Mac)

3. Plugin pack (visible only if no PAT in keychain)
   "Per accedere ai contenuti, incolla il GitHub Personal Access Token che ti è stato fornito."
   [ ___________________________ ]
   [ Verifica e installa ]
```

After step 3 (or skip if PAT already present): the home screen renders. The first sync (catalog, favorites, watchlist, progress, settings) runs in the background; the user can interact with cached data immediately if any.

Re-login from a new device → user re-pastes the same PAT (one PAT per user, reusable across that user's devices).

---

## 12. Build & distribution

### 12.1 Repo topology

| Repo | Visibility | Owner | Contents |
|---|---|---|---|
| `Streamload` | public | alfanowski | FastAPI backend (reduced) |
| `Streamload-Client` | public, NEW | alfanowski | Flutter app + GHA + appcast |
| `streamload-plugins` | PRIVATE | alfanowski | registry.json + plugins/*.js |
| `Streamload-Web` | public, ARCHIVE | alfanowski | v2 web frontend, kept readable until v3 reaches parity |

### 12.2 GHA pipelines

**`Streamload`**: existing Test + Build & Publish (Docker → ghcr.io). Migration `0008` runs on next deploy. No tag-driven release rebuild needed for v3 cutover.

**`Streamload-Client`** (NEW):
- `test-client.yml` — `flutter test` on every push.
- `release-client.yml` — on `v*` tag:
  1. `flutter build macos --release`.
  2. `codesign --force --deep --sign -` (ad-hoc, no Apple Developer yet).
  3. zip → `Streamload-v0.3.0-macos.zip`.
  4. EdDSA-sign the zip (private key in repo secrets).
  5. Create GitHub Release with asset + signature.
  6. Update `appcast.xml` on `gh-pages` branch (commit + push).

### 12.3 Versioning

- Client follows semver. v3 starts at `v0.3.0`.
- `min_app_version` in plugin registry guards against running plugins that need newer host APIs.
- Backend follows independent semver (currently at `v0.2.1`); v3 backend cutover bumps to `v0.3.0`.

### 12.4 Cutover plan

1. Deploy backend `v0.3.0` (with migration `0008`) to the existing VPS.
2. Confirm v2 web (`Streamload-Web`) still functions against the reduced backend (it will lose `/play` and `/stream`; affected pages show graceful errors).
3. Ship `Streamload-Client v0.3.0` as the new primary entry point.
4. After 30 days of stable v3 usage by all 10 users, archive `Streamload-Web` to read-only.

---

## 13. Migration from v2 → v3 for the operator's data

The v2 database tables that survive into v3 keep their data. The operator's bootstrap admin account is preserved by `streamload/api/app.py`'s lifespan. Catalog items + tv_episodes already populated by v2 carry over. `catalog_sources` is dropped — but it never represented user data, only scraped pointers, so no user-visible loss.

---

## 14. Testing strategy

- **Backend**: existing pytest suite (313 tests, 0 failing) as the baseline. Migration `0008` adds tests for the schema changes. Telemetry events route gets a dedicated test file.
- **Client**: `flutter_test` for widgets + `mocktail` for unit tests on use-cases. Integration tests for the HLS proxy via `package:test` against a known fixture playlist. Plugin runtime tests with an in-tree `fixture-plugin.js` exercising every host API surface.
- **Plugin contract conformance**: a CLI tool `tools/lint-plugin.dart` that loads a `.js` and asserts the `meta` schema + presence of all four exported functions + capability enum membership. Run in CI of the private plugin repo before merging.

---

## 15. Risks and open questions

- **flutter_js maturity**: QuickJS via flutter_js is well-tested but its ecosystem is smaller than V8. Risk: complex regex / large HTML parsing perf could be 2-5x slower than Node. Mitigation: keep plugins lean, push HTML pre-filtering server-side… wait, we can't (radioactive). Mitigation: measure on real plugins; if QuickJS is too slow, swap in `flutter_qjs` or fallback to a Rust + WASM scraping core. Decision deferred to first plugin port.
- **media_kit binary size**: libmpv adds ~30 MB to the .app bundle. Acceptable for desktop.
- **Apple notarization deferred**: every release prompts Gatekeeper warning until enrolled. Acceptable for 10 internal users; required before any wider distribution.
- **`auto_updater` on Linux**: less polished than Sparkle. Mitigation: Linux is post-MVP anyway.
- **PAT lifecycle**: if a user leaks their PAT, the operator must rotate it (revoke on GitHub + reissue). Build a "Rotate plugin token" affordance in the admin portal phase.
- **GitHub API rate limits**: with 10 users polling registry.json every 30 min, well under the 5000/hr per-PAT limit. Future-proof if user count grows.

---

## 16. Out-of-scope for v3 MVP (explicitly)

- Mobile (iOS/Android) builds.
- Apple Developer + code signing + notarization.
- Admin web portal (data is collected; portal is a future spec).
- Cast / AirPlay output.
- Skip-intro auto-detection.
- Plex/Jellyfin/Emby integration.
- Subtitles in HLS (deferred — display via `<track>` later).
- Offline download of full episodes for later viewing.
- Multi-user simultaneous playback lockout.

---

## 17. Implementation decomposition guidance

This design covers multiple coupled subsystems but is internally consistent and should be planned as a coordinated effort. The implementation plan should decompose into ~6 sequential sub-plans:

1. **Backend reduction** (migration 0008, drop services/streaming, add user_settings + watch_history + search_history + events tables, ship `Streamload v0.3.0`).
2. **Plugin distribution infrastructure** (create private `streamload-plugins` repo, registry.json schema, plugin file shape, sha256 verification protocol). Initially with a fixture plugin used only for client-side tests.
3. **Client foundation** (new `Streamload-Client` repo, Flutter scaffolding, drift schema, riverpod skeleton, theme port from v2 SvelteKit, login/register screens, ApiClient against the reduced backend).
4. **Plugin runtime** (flutter_js sandbox, host API surface, registry/loader/updater, settings UI for managing plugins).
5. **HLS playback** (Dart shelf proxy, m3u8 rewriter port, media_kit integration, AES decryption, segment cache).
6. **Feature parity + polish** (search, library, title detail with episodes, watch with player overlays, favorites, watchlist, continue-watching, settings, onboarding wizard, auto-updater wiring, telemetry batching, build/sign/release pipeline).

Each sub-plan produces independently shippable work — except #6 which depends on #3, #4, #5 all being merged. Plan #1 can deploy to production at any time after testing without affecting v2 clients beyond the loss of /play and /stream.

## 18. Acceptance criteria (when can we cut v0.3.0?)

- [ ] All 13 v1 plugins ported to JS, hosted in private repo, end-to-end playback verified on Mac.
- [ ] All v2 web user-facing screens (home, search, title, watch, profile, library, login, register) replicated in Flutter at usable parity.
- [ ] Backend reduced (migration 0008 applied); 313 v2 tests still passing minus the deleted ones; new client integration tests passing.
- [ ] Auto-update flow tested end-to-end on a clean Mac (install v0.3.0, push v0.3.1, app self-updates).
- [ ] Plugin pack first-run onboarding tested with a fresh user + fresh PAT.
- [ ] Cross-device resume verified: same user logged in on Mac A → marks progress on a title → opens app on Mac B → progress visible and player resumes from the same position.
- [ ] Telemetry events visible via direct DB query (admin portal not built yet).
- [ ] No reference to upstream domains anywhere in the published `Streamload-Client` source tree (CI lint to enforce).

---

End of design.
