# Streamload v2 — Design Document

**Date**: 2026-05-08
**Status**: Draft for review
**Author**: alfanowski (with brainstorming assistance)
**Supersedes**: `2026-03-17-streamload-design.md` (v1 CLI design)

---

## 1. Executive Summary

Streamload v2 transforms the existing curses-based CLI downloader into a **private Netflix-like streaming platform** accessible over Tailscale. The current Python codebase (services, scrapers, DRM, domain resolver) is preserved as the backend; a new web layer adds:

- **TMDB-driven canonical catalog** with reverse-lookup to all 13 supported services (one title, multiple sources, intelligent ranking).
- **Pure streaming** (HLS proxy + DRM decrypt + restream) — no permanent downloads. RAM ring buffer + disk LRU cache for hiccup recovery.
- **Multi-user web app** (SvelteKit) with self-registration, password + passkey auth, per-user watch progress and favorites.
- **PWA** installable on iOS/Android with Cast (Chromecast) and AirPlay support.
- **Cinematic Dark** visual identity (Apple TV+ inspired, amber accent).

The v1 CLI is **preserved** in parallel for power users; the web app is the primary surface from v2 forward.

### Key constraints

- **Hardware**: dev on MacBook Air M4 (abundant); production on Acer TravelMate B113E (Intel Celeron 877/1007U, 8 GB RAM, 2012 hardware) → all components must be efficient by default.
- **Network**: Tailscale-only (no public internet exposure); one tailnet, multiple devices per user.
- **Legal posture**: identical to v1 CLI personal use (single household behind VPN). No public domain. No commercial intent.

---

## 2. Goals & Non-Goals

### 2.1 Goals

1. **Frictionless playback**: click a title, video starts within ~2 seconds.
2. **Smart aggregation**: same title across multiple services = one canonical entry; system auto-picks the best source per playback session, with manual override available.
3. **Full DRM support**: stream RaiPlay / Mediaset / Crunchyroll content alongside non-DRM sources, transparent to the viewer.
4. **Continue-watching**: watch progress persists per user, cross-source (resume from any service).
5. **Catalog discovery**: home page surfaces TMDB editorial collections (Trending, Popular Movies, Popular TV, Anime, genre rows) populated via reverse-lookup.
6. **Multi-user**: each household member has their own login, progress, favorites, watchlist.
7. **Mobile-first PWA**: usable from iPhone/iPad/Android with native installation, offline UI shell.
8. **Cast support**: AirPlay (Safari native) + Chromecast (Cast SDK).
9. **Aesthetic**: visually polished frontend that doesn't feel like a hobby project.
10. **Self-healing**: domain resolver + circuit breaker continue to work; sources are validated before listing; broken services degrade gracefully.

### 2.2 Non-Goals

1. **Permanent file downloads**: removed. v2 is streaming-only with caching for hiccup recovery, not a downloader.
2. **Public internet exposure**: explicitly out of scope. Tailscale-only.
3. **Native iOS/Android apps**: not in v2. PWA covers 90% of native app value with 10% of the work.
4. **Live TV / linear streaming**: out of scope. v2 is on-demand catalog only.
5. **Ad-supported / commercial mode**: out of scope.
6. **Real-time co-watching ("watch parties")**: out of scope for v2.
7. **Trakt / IMDb / Letterboxd integration**: out of scope for v2 (TMDB is the only metadata provider).
8. **Recommendation engine**: out of scope for v2. Beyond "Continue Watching" and TMDB editorial rows, no personalized recommendations.
9. **CDN edge caching**: not needed (single-user, single-server).
10. **Horizontal scaling**: not needed (max 5-10 concurrent streams ever).

---

## 3. Hardware & Performance Targets

### 3.1 Production hardware

- **Acer TravelMate B113E** (~2012)
- CPU: Intel Celeron 877 (Sandy Bridge, 2c/2t, 1.4 GHz, no Quick Sync) or 1007U (Ivy Bridge, 2c/2t, 1.5 GHz, Quick Sync 3rd gen)
- RAM: 8 GB DDR3
- Storage: assumed 250-500 GB SSD or HDD upgrade
- OS: Linux (Ubuntu Server LTS or similar lightweight distro)
- Network: Gigabit Ethernet on home LAN

### 3.2 Performance targets

| Metric | Target | Reasoning |
|---|---|---|
| Time to first frame after Play click | ≤ 2.5 s | Includes resolve + extract + first segment fetch |
| Catalog refresh duration (full) | ≤ 90 s | Background, async, runs once per 24 h |
| Home page Time-To-Interactive (mobile WiFi) | ≤ 800 ms | SvelteKit SSR + small JS bundle |
| Frontend JS bundle (gzipped, after compile) | ≤ 50 KB | SvelteKit + Vidstack only |
| Concurrent streams sustained on Acer | 3-4 (non-DRM), 1-2 (DRM) | DRM decrypt is CPU-bound |
| Memory baseline (idle) | ≤ 1 GB resident | Leaves headroom for OS + cache |
| Memory peak (3 concurrent streams) | ≤ 4 GB resident | RAM buffers + connection pools |
| Disk cache size (default) | 30 GB LRU | Configurable; eviction by access time |

### 3.3 Efficiency-driven architectural choices

- **Granian** (Rust ASGI server) instead of Uvicorn → 30-40% lower CPU at equivalent throughput.
- **uvloop** for asyncio event loop → 30% lower latency on async I/O.
- **httpx async** (not blocking) throughout the request path.
- **Connection pooling** for outbound HTTP (one pool per host).
- **HTTP/2** for upstream when supported (multiplexes segment fetches).
- **Server-side rendering** for the home page → no client-side hydration burst.
- **Lazy hydration** for non-critical components.
- **Static SvelteKit build** served by FastAPI (no separate Node frontend server in production).
- **No transcoding** — pure HLS pass-through (segment-level proxy).
- **Aggressive segment caching** — RAM ring buffer (last 30 s) + disk LRU (last N hours).

---

## 4. Architecture Overview

### 4.1 High-level component map

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Browser / PWA                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │  Home    │  │ Library  │  │  Detail  │  │  Player  │  │  Auth  │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └────────┘ │
│                          SvelteKit + Vidstack                        │
└────────────────────────────────────┬────────────────────────────────┘
                                     │ HTTPS (Tailscale)
                                     │
┌────────────────────────────────────▼────────────────────────────────┐
│                       FastAPI (Python 3.11+)                          │
│  ┌────────┐  ┌─────────┐  ┌───────────┐  ┌──────────┐  ┌──────────┐ │
│  │  Auth  │  │ Catalog │  │  Sources  │  │ Streaming│  │   PWA    │ │
│  │ Routes │  │ Routes  │  │  Routes   │  │   Proxy  │  │  Static  │ │
│  └────────┘  └─────────┘  └───────────┘  └──────────┘  └──────────┘ │
│      │           │              │              │              │      │
│  ┌───▼───────────▼──────────────▼──────────────▼──────────────▼───┐  │
│  │                    Core Service Layer                           │  │
│  │  ┌────────────┐  ┌─────────────┐  ┌──────────────┐             │  │
│  │  │   TMDB     │  │  Source     │  │  DRM /       │             │  │
│  │  │  Client    │  │  Ranker     │  │  Decrypt     │             │  │
│  │  └────────────┘  └─────────────┘  └──────────────┘             │  │
│  │  ┌────────────────────────────────────────────────┐            │  │
│  │  │     Existing v1 backend (preserved 100%)        │            │  │
│  │  │  services/  player/  core/  utils/  models/    │            │  │
│  │  └────────────────────────────────────────────────┘            │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                     │                                 │
└────────────────────────────────────┬┴────────────────────────────────┘
                                     │
        ┌────────────┬───────────────┼─────────────────┬──────────────┐
        │            │               │                 │              │
   ┌────▼────┐  ┌───▼─────┐   ┌─────▼──────┐   ┌──────▼──────┐  ┌────▼───┐
   │ Postgres│  │ Disk    │   │  TMDB API  │   │  Scraper    │  │ Tailnet│
   │  (data) │  │ Cache   │   │ (metadata) │   │  Targets    │  │ (vpn)  │
   │         │  │ (~30GB) │   │            │   │  (13 sites) │  │        │
   └─────────┘  └─────────┘   └────────────┘   └─────────────┘  └────────┘
```

### 4.2 Layer responsibilities

| Layer | Responsibility | Existing or New |
|---|---|---|
| **SvelteKit frontend** | Pages, player UI, PWA shell, cast integration, state mgmt | New |
| **FastAPI HTTP layer** | REST routes, websocket for progress, static SvelteKit build | New |
| **Streaming Proxy** | HLS rewrite, segment fetch + cache, DRM decrypt + remux | New |
| **Catalog Service** | TMDB ingestion, reverse lookup, collections, dedup | New |
| **Source Ranker** | Score sources by quality+latency+reliability+audio+subs | New |
| **Auth Service** | Argon2 passwords + WebAuthn passkeys + sessions | New |
| **DRM Subsystem** | Widevine/PlayReady CDM, key extraction, segment decrypt | Wraps existing `core/drm/` |
| **Service Adapters** | 13 existing scrapers (search, get_streams, get_seasons) | Existing v1, untouched |
| **Domain Resolver** | 5-source chain, signed manifest, FHD upgrade | Existing v1, untouched |
| **HTTP Client** | curl_cffi + httpx with retry & TLS impersonation | Existing v1, refactor to async-first |

### 4.3 Tech stack summary

**Backend**
- Python 3.11+
- FastAPI 0.115+
- Granian 1.x (Rust ASGI server, replaces Uvicorn)
- SQLAlchemy 2.x async + asyncpg
- Alembic (migrations)
- uvloop (event loop)
- httpx async + curl_cffi (existing) + aiohttp where needed
- argon2-cffi (password hashing)
- webauthn (FIDO2/passkey support)
- pywidevine + pyplayready (existing, server-side decrypt)
- PIL + httpx for image proxy/cache

**Frontend**
- SvelteKit (Svelte 5, runes mode)
- TypeScript strict
- Tailwind CSS v4
- Vidstack (video player, framework-agnostic)
- Lucide icons (Svelte port)
- Workbox / vite-plugin-pwa (service worker)
- Cast Sender SDK (Google) for Chromecast
- AirPlay: zero JS (Safari native)

**Infrastructure**
- PostgreSQL 16+ (existing instance)
- Tailscale (existing, MagicDNS enabled)
- systemd unit on Linux for production
- Optional: Caddy as reverse proxy (HTTP/2 termination, automatic TLS for Tailscale Funnel if ever desired)

---

## 5. Data Model

### 5.1 PostgreSQL schema

Designed to be **lean**: 9 tables total, no orphaned metadata, no redundant indexes.

```sql
-- ============================================================
-- USERS & AUTH
-- ============================================================

CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username            TEXT NOT NULL UNIQUE,
    email               TEXT NOT NULL UNIQUE,            -- required (used for verification + reset)
    email_verified_at   TIMESTAMPTZ,                     -- NULL until user clicks verification link
    email_required      BOOLEAN NOT NULL DEFAULT TRUE,   -- admin-only override (see §16.4)
    password_hash       TEXT,                            -- argon2id, NULL if passkey-only
    role                TEXT NOT NULL DEFAULT 'user',    -- 'admin' | 'user'
    locale              TEXT NOT NULL DEFAULT 'it-IT',
    avatar_url          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at       TIMESTAMPTZ,
    CHECK (role IN ('admin', 'user'))
);

-- Email verification + password reset tokens (see §16)
CREATE TABLE email_tokens (
    token_hash      BYTEA PRIMARY KEY,                 -- sha256(opaque_token)
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose         TEXT NOT NULL,                     -- 'verify_email' | 'reset_password'
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ,                       -- NULL = unused
    CHECK (purpose IN ('verify_email', 'reset_password'))
);

CREATE INDEX idx_email_tokens_user ON email_tokens(user_id);

CREATE TABLE webauthn_credentials (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id   BYTEA NOT NULL UNIQUE,             -- raw FIDO2 credential ID
    public_key      BYTEA NOT NULL,                    -- COSE-encoded
    sign_count      INTEGER NOT NULL DEFAULT 0,
    transports      TEXT[] NOT NULL DEFAULT '{}',      -- ['internal', 'usb', ...]
    nickname        TEXT,                              -- "iPhone 15", "MacBook TouchID"
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ
);

CREATE TABLE sessions (
    token_hash      BYTEA PRIMARY KEY,                 -- sha256(opaque_token)
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_agent      TEXT,
    ip_address      INET,
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_expires_at ON sessions(expires_at);

-- ============================================================
-- CATALOG (TMDB-driven canonical entries)
-- ============================================================

CREATE TABLE catalog_items (
    tmdb_id         INTEGER PRIMARY KEY,               -- The Movie DB ID (universally unique per type)
    media_type      TEXT NOT NULL,                     -- 'movie' | 'tv'
    title           TEXT NOT NULL,
    original_title  TEXT,
    year            INTEGER,
    poster_url      TEXT,                              -- TMDB CDN URL
    backdrop_url    TEXT,                              -- TMDB CDN URL
    overview        TEXT,                              -- localized plot
    rating          NUMERIC(3,1),                      -- TMDB vote_average
    runtime_minutes INTEGER,                           -- movies only
    seasons_count   INTEGER,                           -- TV only
    genres          TEXT[] NOT NULL DEFAULT '{}',
    metadata_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (media_type IN ('movie', 'tv'))
);

CREATE INDEX idx_catalog_items_year ON catalog_items(year);
CREATE INDEX idx_catalog_items_genres ON catalog_items USING GIN(genres);

CREATE TABLE catalog_sources (
    tmdb_id              INTEGER NOT NULL REFERENCES catalog_items(tmdb_id) ON DELETE CASCADE,
    service_short_name   TEXT NOT NULL,                -- 'sc', 'au', 'rp', etc.
    service_url          TEXT NOT NULL,                -- canonical URL on the service
    service_media_id     TEXT NOT NULL,                -- service-internal ID
    quality_max_height   INTEGER,                      -- 480, 720, 1080
    languages_audio      TEXT[] NOT NULL DEFAULT '{}', -- ISO codes: ['ita', 'eng']
    languages_subs       TEXT[] NOT NULL DEFAULT '{}',
    last_verified_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    success_count        INTEGER NOT NULL DEFAULT 0,
    failure_count        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tmdb_id, service_short_name)
);

CREATE INDEX idx_catalog_sources_service ON catalog_sources(service_short_name);

-- ============================================================
-- COLLECTIONS (TMDB editorial rows shown on home)
-- ============================================================

CREATE TABLE collections (
    id              TEXT PRIMARY KEY,                  -- 'trending-day', 'popular-movies', 'popular-tv', 'anime-season', 'top-rated'
    title           TEXT NOT NULL,                     -- 'Trending oggi', 'Film popolari', ...
    media_type      TEXT,                              -- 'movie' | 'tv' | NULL (any)
    sort_order      INTEGER NOT NULL,                  -- display order on home
    refresh_ttl_hours INTEGER NOT NULL DEFAULT 24,
    last_refreshed_at TIMESTAMPTZ
);

CREATE TABLE collection_items (
    collection_id   TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    tmdb_id         INTEGER NOT NULL REFERENCES catalog_items(tmdb_id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,                  -- order within the row
    PRIMARY KEY (collection_id, tmdb_id)
);

CREATE INDEX idx_collection_items_collection ON collection_items(collection_id, position);

-- ============================================================
-- TV-specific: episodes (so resume + auto-play next work)
-- ============================================================

CREATE TABLE tv_episodes (
    tmdb_id         INTEGER NOT NULL REFERENCES catalog_items(tmdb_id) ON DELETE CASCADE,
    season_number   INTEGER NOT NULL,
    episode_number  INTEGER NOT NULL,
    title           TEXT,
    overview        TEXT,
    air_date        DATE,
    runtime_minutes INTEGER,
    still_url       TEXT,                              -- TMDB CDN
    PRIMARY KEY (tmdb_id, season_number, episode_number)
);

-- ============================================================
-- USER STATE
-- ============================================================

CREATE TABLE watch_progress (
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tmdb_id         INTEGER NOT NULL REFERENCES catalog_items(tmdb_id) ON DELETE CASCADE,
    season_number   INTEGER,                           -- NULL for movies
    episode_number  INTEGER,                           -- NULL for movies
    position_seconds INTEGER NOT NULL,
    duration_seconds INTEGER NOT NULL,
    completed       BOOLEAN NOT NULL DEFAULT FALSE,    -- true when position >= 0.9 * duration
    last_source     TEXT,                              -- service_short_name last used
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, tmdb_id, COALESCE(season_number, 0), COALESCE(episode_number, 0))
);

CREATE INDEX idx_watch_progress_user_recent ON watch_progress(user_id, updated_at DESC) WHERE completed = FALSE;

CREATE TABLE favorites (
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tmdb_id         INTEGER NOT NULL REFERENCES catalog_items(tmdb_id) ON DELETE CASCADE,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, tmdb_id)
);

CREATE TABLE watchlist (
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tmdb_id         INTEGER NOT NULL REFERENCES catalog_items(tmdb_id) ON DELETE CASCADE,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, tmdb_id)
);

-- ============================================================
-- INTRO/OUTRO MARKERS (per series, fingerprinted)
-- ============================================================

CREATE TABLE intro_markers (
    tmdb_id         INTEGER NOT NULL REFERENCES catalog_items(tmdb_id) ON DELETE CASCADE,
    season_number   INTEGER NOT NULL,
    intro_start_seconds INTEGER NOT NULL,
    intro_end_seconds   INTEGER NOT NULL,
    outro_start_seconds INTEGER,
    detected_by     TEXT NOT NULL,                     -- 'fingerprint' | 'manual'
    confidence      NUMERIC(3,2),                      -- 0.00 - 1.00 for fingerprint
    PRIMARY KEY (tmdb_id, season_number)
);

-- ============================================================
-- AUDIT (lean, append-only)
-- ============================================================

CREATE TABLE playback_events (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    tmdb_id         INTEGER,
    event_type      TEXT NOT NULL,                     -- 'play_start', 'play_end', 'source_switch', 'error'
    source          TEXT,                              -- service_short_name
    metadata        JSONB,                             -- flexible payload
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_playback_events_user ON playback_events(user_id, occurred_at DESC);
```

**Total: 12 tables.** Schema is deliberately minimal — no denormalization, no precomputed aggregates, no unused indexes. Postgres handles 100k catalog items + 100k events easily.

### 5.2 Disk artifacts

Outside the database:

```
data/
├── domains_cache.json          (existing, v1 domain resolver)
├── cache/
│   ├── segments/               LRU disk cache for HLS segments (~30 GB target)
│   ├── posters/                TMDB poster images mirror (~500 MB)
│   ├── backdrops/              TMDB backdrops mirror (~1 GB)
│   └── audio_fingerprints/     intro detection cache (~50 MB)
└── secret/                     existing (gitignored, signing key)
```

### 5.3 Schema migrations

- **Alembic** as the migration tool.
- Initial migration `0001_initial_schema.py` creates the full schema above.
- Subsequent migrations are forward-only; rollback supported only for the last migration during dev.
- Migrations run automatically on app startup (idempotent — Alembic checks current revision).

---

## 6. Backend Components

### 6.1 Catalog Service

**Responsibility**: maintain a TMDB-canonical catalog with reverse-lookup to all 13 service adapters.

**Files** (new package `streamload/catalog/`):

- `tmdb.py`: TMDB API client (async, retries, image URL builder).
- `ingest.py`: collection refresh logic (fetch TMDB → resolve sources → upsert).
- `match.py`: title-to-service matching (fuzzy match: normalized title + year + ±1 year tolerance).
- `collections.py`: definitions of which TMDB endpoints map to which home rows.
- `service.py`: high-level facade (`get_catalog_item(tmdb_id)`, `search(query)`, `refresh_collection(id)`).

**Collections defined for v1** (mapped to TMDB endpoints):

| `id` | Title | TMDB endpoint | media_type | TTL |
|---|---|---|---|---|
| `continue-watching` | Continua a guardare | (per-user, computed) | any | live |
| `favorites` | I tuoi preferiti | (per-user) | any | live |
| `trending-day` | Trending oggi | `/trending/all/day` | any | 6h |
| `popular-movies` | Film popolari | `/movie/popular` | movie | 24h |
| `popular-tv` | Serie TV popolari | `/tv/popular` | tv | 24h |
| `anime-season` | Anime di stagione | `/discover/tv?with_genres=16&with_origin_country=JP&air_date.gte=...` | tv | 24h |
| `top-rated-all-time` | Top rated di sempre | `/movie/top_rated` | movie | 7d |
| `genre-action` | Azione | `/discover/movie?with_genres=28&sort_by=popularity.desc` | movie | 24h |
| `genre-horror` | Horror | `/discover/movie?with_genres=27&sort_by=popularity.desc` | movie | 24h |
| `genre-scifi` | Sci-Fi & Fantasy | `/discover/movie?with_genres=878,14&sort_by=popularity.desc` | movie | 24h |

(Final list of genre rows configurable; this is a starter set.)

**Reverse-lookup flow** (the heart of the design):

```python
async def ingest_collection(collection_id: str):
    # 1. Fetch TMDB collection (e.g., 20 popular movies)
    tmdb_items = await tmdb.fetch_collection(collection_id)  # 1 HTTP

    # 2. Upsert canonical metadata
    for item in tmdb_items:
        await catalog.upsert_item(item)  # localized poster, plot, runtime

    # 3. For each item, find which services have it
    async with asyncio.Semaphore(8):  # 8 parallel reverse lookups
        for item in tmdb_items:
            sources_found = []
            for service in service_registry.all():
                # service.search() already exists in v1!
                results = await service.search_async(item.title)
                # match by title similarity + year proximity
                match = match.best(results, target_title=item.title, target_year=item.year)
                if match:
                    sources_found.append((service, match))

            await catalog.upsert_sources(item.tmdb_id, sources_found)

    # 4. Update collection_items with new positions
    await catalog.update_collection_membership(collection_id, [i.tmdb_id for i in tmdb_items])

    # 5. Mark collection as refreshed
    await catalog.touch_collection(collection_id)
```

**Schedule**: refresh runs in a background task (FastAPI lifespan) every N hours per collection's TTL. Plus: triggered manually via `POST /api/admin/collections/{id}/refresh`.

**Cost**: 100 titles × 13 services = ~1300 HTTP requests per full refresh, parallelized 8-way → ~30 seconds wall clock. Doesn't block user requests.

### 6.2 Source Ranker

**Responsibility**: given a list of `(service, source_metadata)` tuples for a single canonical title, score them and return the ranked list. Used at playback time to pick "Server 1, Server 2, Server 3".

**Inputs per source**:
- `quality_max_height` (1080, 720, 480) — from cached scrape
- `latency_ttfb_ms` (avg time-to-first-byte, rolling window of last N attempts)
- `success_rate` (success_count / (success+failure), with exponential decay favoring recent)
- `audio_languages` (presence of 'ita', 'eng', 'jpn', etc.)
- `subtitle_languages`
- DRM flag (some users may prefer non-DRM sources for performance)

**Scoring** (weighted sum, normalized 0-100):

```
score = (
    0.40 * quality_score        # 1080p=100, 720p=70, 480p=40, lower=20
  + 0.20 * latency_score        # exp decay; <500ms=100, 1500ms=70, 3000ms=40, ...
  + 0.20 * reliability_score    # success_rate * 100
  + 0.10 * audio_match_score    # 100 if user's preferred lang available, else 50
  + 0.10 * subtitle_match_score # 100 if user's preferred lang available, else 50
)
```

Weights configurable via `config.json` per user preference (e.g., a user who prioritizes audio language over quality can shift weights to 0.20/0.10/0.10/0.40/0.20).

**Tie-breaking**: when scores are within 5 points, prefer the source with longer recent verification (last_verified_at).

**"Server N" labeling**: the ranked list is presented as `Server 1`, `Server 2`, `Server 3` — never the actual service name. The mapping is per-title and per-session: same title later may have a different "Server 1" if rankings shift.

**File**: `streamload/catalog/ranker.py`.

### 6.3 Streaming Proxy

**Responsibility**: the heart of v2. Given a canonical title + selected source, expose endpoints that let the browser play the stream as if it came from your domain.

#### 6.3.1 Endpoint structure

```
GET  /api/play/{tmdb_id}?source=auto                    → returns playback session
GET  /stream/{session_id}/master.m3u8                   → HLS master playlist (rewritten)
GET  /stream/{session_id}/audio/{lang}.m3u8             → audio rendition
GET  /stream/{session_id}/sub/{lang}.vtt                → subtitle rendition (WebVTT)
GET  /stream/{session_id}/video/{height}.m3u8           → video rendition
GET  /stream/{session_id}/seg/{rendition}/{n}.ts        → segment proxy
```

**Why session-scoped**: each playback gets a unique `session_id` (UUID). Tokens to upstream are stored in session state (Redis-style in memory, expire after 4 hours). Segment URLs in the rewritten manifest reference your backend with the session_id, never the upstream.

#### 6.3.2 Playback session lifecycle

```python
@router.post("/api/play/{tmdb_id}")
async def start_playback(tmdb_id: int, source: str = "auto", user: User = Depends(...)):
    # 1. Resolve title
    item = await catalog.get(tmdb_id)
    sources = await catalog.get_sources(tmdb_id)

    # 2. Pick source
    if source == "auto":
        ranked = ranker.rank(sources, user_prefs=user.preferences)
        chosen = ranked[0]
    else:
        chosen = next(s for s in sources if s.label == source)  # 'server-1', 'server-2'

    # 3. Extract upstream playlist (existing v1 code)
    service = service_registry.get(chosen.service_short_name)
    bundle = await service.get_streams_async(chosen.media_id)

    # 4. Create session
    session = playback_sessions.create(
        user_id=user.id,
        tmdb_id=tmdb_id,
        upstream_master_url=bundle.manifest_url,
        upstream_headers=bundle.extra_headers,
        is_drm=bundle.is_drm,
        decrypt_keys=bundle.drm_keys if bundle.is_drm else None,
        ttl=4*3600,
    )

    # 5. Return URLs to client
    return {
        "session_id": session.id,
        "master_url": f"/stream/{session.id}/master.m3u8",
        "subtitles": [{"lang": s.lang, "url": f"/stream/{session.id}/sub/{s.lang}.vtt"} for s in bundle.subtitles],
        "ranked_servers": [{"label": f"Server {i+1}", "service": s.service_short_name, "score": s.score} for i, s in enumerate(ranked)],
        "current_server": chosen.label,
    }
```

#### 6.3.3 Master playlist rewrite

When the browser fetches `/stream/{session_id}/master.m3u8`:

```python
@router.get("/stream/{session_id}/master.m3u8")
async def proxy_master(session_id: UUID):
    session = playback_sessions.get(session_id)
    upstream_text = await fetch_upstream(session.upstream_master_url, session.upstream_headers)

    # Rewrite the master playlist:
    # - Replace each rendition URL with /stream/{session_id}/video/{height}.m3u8
    # - Replace each audio URL with /stream/{session_id}/audio/{lang}.m3u8
    # - Replace each subtitle URL with /stream/{session_id}/sub/{lang}.vtt
    rewritten = m3u8_rewrite.master(upstream_text, base=f"/stream/{session_id}/")

    return Response(rewritten, media_type="application/x-mpegURL")
```

#### 6.3.4 Segment proxy with cache

```python
@router.get("/stream/{session_id}/seg/{rendition}/{n}.ts")
async def proxy_segment(session_id: UUID, rendition: str, n: int):
    session = playback_sessions.get(session_id)

    # 1. Check disk LRU
    cache_key = f"{session.upstream_master_url}#{rendition}#{n}"
    cached = await disk_cache.get(cache_key)
    if cached:
        return StreamingResponse(cached, media_type="video/mp2t")

    # 2. Fetch upstream
    upstream_seg_url = session.resolve_segment(rendition, n)
    upstream_bytes = await fetch_upstream_bytes(upstream_seg_url, session.upstream_headers)

    # 3. If DRM, decrypt
    if session.is_drm:
        upstream_bytes = drm.decrypt_segment(upstream_bytes, keys=session.decrypt_keys)

    # 4. Cache and return
    await disk_cache.set(cache_key, upstream_bytes, ttl=3600)
    return Response(upstream_bytes, media_type="video/mp2t")
```

**RAM ring buffer**: an LRU dict in memory holds the last ~30 segments per active session. Hits avoid disk.

**Concurrent prefetch**: when a segment is requested, a background task pre-fetches the next 3 segments speculatively.

**Disk LRU eviction**: configurable size (default 30 GB). LRU by access time, evicted asynchronously.

#### 6.3.5 DRM segment decryption flow

For services where `bundle.is_drm == True`:

```python
async def get_streams_async(self, item):
    bundle = await super_get_streams(item)  # existing v1 flow
    if bundle.is_drm:
        # Existing v1 flow already extracts the PSSH from the manifest
        # and exchanges with the CDM (pywidevine / pyplayready)
        bundle.drm_keys = await drm.fetch_keys(
            pssh=bundle.pssh,
            license_url=bundle.license_url,
            cdm_type=bundle.cdm_type,
        )
    return bundle


def decrypt_segment(encrypted: bytes, keys: list[ContentKey]) -> bytes:
    # AES-128-CTR or CBC depending on protection scheme.
    # Existing v1 decryption code (lives in core/drm/decrypt.py).
    return existing_drm.decrypt(encrypted, keys)
```

The browser receives **plaintext HLS segments**. It never sees DRM tokens, license URLs, or upstream service URLs. From the browser's perspective, the entire stream is "plain HLS from streamload.<tailnet>.ts.net".

### 6.4 Auth Service

**Responsibility**: user accounts, password + passkey login, sessions.

**Files**: `streamload/auth/`:
- `passwords.py`: argon2id hashing (`argon2-cffi`), constant-time compare.
- `passkeys.py`: WebAuthn registration + authentication using `webauthn` library.
- `sessions.py`: opaque token issuance, hashed-token DB lookup, sliding expiration.
- `routes.py`: FastAPI dependency `Depends(current_user)`, login/logout/register routes.

**Self-registration flow** (open per design decision):

```
POST /api/auth/register
  body: { username, email?, password, displayName? }
  ↓ creates user with role='user'
  ↓ optionally requires passkey enrollment
  ↓ issues session cookie
```

**First user becomes admin** automatically (no users in DB → role='admin').

**Passkey registration** (after login or as part of registration):

```
1. POST /api/auth/passkey/options       → server returns challenge
2. browser navigator.credentials.create()  → user TouchID/FaceID
3. POST /api/auth/passkey/verify        → server verifies + stores public key
```

**Login flows**:

```
A. Password:
   POST /api/auth/login {username, password}
     → argon2.verify, issue session cookie

B. Passkey:
   POST /api/auth/passkey/challenge {username?}  → server returns challenge
   browser navigator.credentials.get()           → user authenticates
   POST /api/auth/passkey/verify {assertion}     → verify + issue cookie

C. Passkey usernameless (autofill):
   browser triggers conditional UI on username field
   user picks passkey from autocomplete
   posts assertion → server identifies user from credential ID
```

**Session token**:
- 32-byte random opaque (base64url, ~43 chars)
- Stored in DB hashed (sha256)
- Cookie: `Set-Cookie: session=<token>; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000` (30 days, sliding)
- Expires_at refreshed on every authenticated request (only if last refresh > 5 min ago, to limit DB writes)

**CSRF**: state-changing requests require either:
- SameSite=Lax cookie (covers most cases)
- For non-Lax-safe ops (e.g., DELETE): explicit CSRF token in header, validated against session

**Rate limiting** on login endpoints: max 10 attempts per IP per 5 min; max 5 per username per 5 min. (In-memory token bucket — no Redis dependency.)

### 6.5 Watch Progress

**Responsibility**: persist + retrieve playback position per user per title (with episode granularity for series).

**Heartbeat** from frontend:
- Player sends `POST /api/progress` every **15 seconds** with `{tmdb_id, season?, episode?, position_seconds, source}`.
- Also fires on pause, on seek, on tab visibility change, on close (`navigator.sendBeacon`).
- Server upserts row in `watch_progress` table.

**Mark-as-watched**:
- When `position / duration >= 0.90` → set `completed = TRUE`.
- Completed items disappear from "Continua a guardare" row.
- For TV series, when episode N is completed, episode N+1 is auto-suggested in the post-roll.

**Resume cross-source**:
- Watch position is per `(user, tmdb_id, season, episode)`, NOT per source.
- If user watched 30 min on "Server 1" (e.g., SC) and tomorrow Server 1 is down, "Server 2" (RaiPlay) resumes from min 30 transparently.
- If the duration differs slightly between sources (e.g., +30s ad on RaiPlay), we resume to the *time*, not to a percentage. Browser player handles the offset gracefully.

**Auto-play next episode** (per design decision yes):
- Player overlay shows countdown 10s before the end of the current episode.
- Card with next episode's title + thumbnail + "Skip" + "Play Now".
- If user does nothing, transitions to next episode at credits start (or at 95% duration if no outro_marker).

### 6.6 Skip Intro / Outro

**v1 approach**: audio-fingerprint based, no ML model needed.

**Algorithm**:
1. When the first 2 episodes of a series are played, compute audio fingerprint of the first 90 seconds of each (using `chromaprint` or `pyacoustid`).
2. Compare fingerprints — the longest matching subsequence (typically 60-90s of opening music) is the intro.
3. Mark `intro_start` and `intro_end` in `intro_markers` table (per `tmdb_id, season_number`).
4. Subsequent episodes: player shows "Skip Intro" button at `intro_start - 2s`, dismisses at `intro_end + 1s`.

**Outro detection**: same algorithm on the last 5 minutes of episodes 2 vs N. If a stable matching segment is found at the end → that's the outro.

**Manual override**: power user can edit markers via a "More options → Adjust intro markers" UI.

**Quality threshold**: only auto-mark if fingerprint match confidence > 0.85. Otherwise no markers shown.

**File**: `streamload/post/intro_detect.py`. Async task triggered when 2nd episode in a series finishes playing.

### 6.7 Domain Resolver Integration

**Unchanged from v1**. The resolver continues to provide `service.base_url` for each scrape; it operates transparently. The `streamload-domains.py` CLI remains available for ops.

**Observability addition**: the domain resolver logs are surfaced in an admin-only `/api/admin/health` endpoint that shows:
- Per-service current resolved domain + source ('config'|'cache'|'remote'|'probe'|'discovery')
- Last manifest fetch timestamp + signature key_id
- Circuit breaker state
- FHD-preferred mirror per service

---

## 7. Frontend Components

### 7.1 Page structure

```
/                              Home (auth required → /login else)
/login                         Username+password OR passkey form
/register                      Open registration
/library                       Browse all catalog (filters: genre, year, type)
/library/movies                Movies only
/library/tv                    TV only
/library/anime                 Anime only (TV with origin_country=JP)
/title/{tmdb_id}               Title detail (poster, plot, episodes if TV, ranked sources, play button)
/watch/{tmdb_id}               Player page (movie)
/watch/{tmdb_id}/s{n}/e{m}     Player page (episode)
/search?q=...                  Search results (live query → fuzzy match TMDB + reverse lookup)
/profile                       User settings (audio/sub language preference, ranker weights)
/settings                      App settings (admin: catalog refresh trigger, user mgmt)
/passkeys                      Manage passkeys (add/remove)
```

### 7.2 Visual design system

**Identity**: "Cinematic Dark" (Apple TV+ inspired)
- **Background**: `#0a0a0a` (near-black, not pure)
- **Surface elevation**: `#141414`, `#1a1a1a`, `#202020` for layered cards
- **Text primary**: `#ffffff`, secondary: `rgba(255,255,255,0.65)`, tertiary: `rgba(255,255,255,0.4)`
- **Accent (amber/gold)**: `#d4a574` — primary buttons, "Play" CTA, focus rings, progress fill
- **Accent hover**: `#e0b889`
- **Critical (red)**: `#ff4d4d` — error states only, used sparingly
- **Borders**: `rgba(255,255,255,0.08)` — barely visible separators

**Typography**:
- Body: `-apple-system, BlinkMacSystemFont, "SF Pro Display", "Inter", sans-serif`
- Headings: same family, weight 700, tight letter-spacing (`-0.02em`)
- Tabular figures for ratings, runtime, year (`font-variant-numeric: tabular-nums`)
- No serif (Editorial Cinema not chosen).

**Spacing scale**: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96 px (matches Tailwind defaults)

**Card patterns**:
- **Poster card** (library, rows): aspect-ratio 2/3, border-radius 6px, on hover: subtle scale(1.04) + brightness(1.1) + slight glow shadow.
- **Hero card** (home top): full-width-ish, aspect-ratio 16/7 on desktop, 16/9 on mobile, backdrop-blur on text overlay.
- **Episode card**: aspect-ratio 16/9 with title + episode number + duration bar.

**Animation**:
- Page transitions via View Transitions API (graceful fallback for non-supporting browsers).
- Microinteractions ≤ 200ms with `cubic-bezier(0.16, 1, 0.3, 1)` (Apple's standard curve).
- Skeleton loaders with shimmer for poster grids during fetch.
- No bouncy/spring animations — Apple TV+ is restrained.

**Responsive breakpoints** (Tailwind defaults adapted):
- Mobile: < 640px (iPhone SE → iPhone 16 Pro Max in portrait)
- Tablet: 640-1024px (iPad in portrait, iPhone in landscape)
- Desktop: 1024-1536px (most laptops, desktop monitors)
- Large: > 1536px (4K monitors)

**Dark mode only**: no light theme in v1 (it's a streaming app, dark is the default everywhere; Apple TV+ doesn't even offer light).

### 7.3 Key components

(Built as Svelte 5 components in runes mode.)

- **`<PosterCard tmdb_id={n} />`** — used in rows, library grid, search results. Lazy-loads image, shows title on hover.
- **`<HeroSection title={item} />`** — home top hero, full-bleed backdrop, title + meta + Play CTA.
- **`<Row title="..." items={list} />`** — horizontal scrolling row of poster cards. Snap-scroll on mobile, smooth-scroll-to on desktop arrow keys.
- **`<Player session={...} />`** — wraps Vidstack with custom skin. Server selector dropdown ("Server 1 ▼"), audio/sub menus, intro skip overlay, next-episode countdown.
- **`<NavBar />`** — top: logo + nav links + search icon + profile dropdown. Sticky, blurs on scroll.
- **`<MobileTabBar />`** — bottom nav on mobile (Home, Search, Library, Profile).
- **`<TitleDetail tmdb_id={n} />`** — full-page detail view. Backdrop hero, poster, plot, ranked sources accordion, episode list (TV), related titles.
- **`<SearchOverlay />`** — full-screen search overlay with autosuggest, recent searches (per user, in localStorage).

### 7.4 State management

**Svelte stores** (rune-based):
- `currentUser` — auth state, syncs from server on app boot.
- `playbackSession` — active session info if any.
- `userPreferences` — audio lang, sub lang, ranker weights, theme.
- `cachedCatalog` — small in-memory cache of recently-viewed catalog items (avoids refetch on back navigation).

**Server state**: TanStack Query (Svelte port) for HTTP fetching with stale-while-revalidate semantics.

**Persistent state**: cookies for auth, localStorage for non-sensitive preferences (last-watched filter, search history).

### 7.5 Player (Vidstack)

**Vidstack** chosen over video.js for: 
- Modern (Svelte/React/HTML, framework-agnostic)
- Smaller bundle
- Better TypeScript types
- Built-in HLS via hls.js, DASH via dash.js (if ever needed)
- Theming via CSS custom properties (matches our design system natively)
- Native AirPlay icon visibility (zero JS for AirPlay)

**Custom skin** matching the visual identity:
- Top overlay (gradient): title + episode + "Server N ▼" dropdown
- Bottom controls (gradient): play/pause + scrub + time + audio + sub + Cast + AirPlay (Safari) + fullscreen + settings
- Settings menu: quality lock (Auto / 1080p / 720p / 480p), playback speed (0.5x to 2x), advanced (intro/outro markers edit)
- Skip intro pill: bottom-right, appears `intro_start - 2s`, fades out `intro_end + 1s`
- Next-episode card: bottom-right, last 10s of episode, with countdown ring + "Salta" + "Riproduci ora"

**Cast integration**:
- Cast Sender SDK loaded conditionally (only when Cast device detected via `chrome.cast` API)
- AirPlay: Safari's native button is preserved (Vidstack doesn't strip it)

**Keyboard shortcuts** (desktop):
- Space: play/pause
- ← → : seek -10/+10s
- ↑ ↓ : volume
- F: fullscreen
- M: mute
- C: cycle subtitle tracks
- A: cycle audio tracks
- N: next episode
- ?: show shortcuts overlay

### 7.6 Routing & Auth Guards

- All routes under `/` require auth except `/login`, `/register`, `/api/auth/*`, `/api/health`.
- Auth check via SvelteKit `+layout.server.ts` — runs on every route, redirects to `/login` if cookie missing/invalid.
- Admin-only routes (`/settings/admin/*`): additional guard for `user.role === 'admin'`.

---

## 8. Network & Streaming Architecture

### 8.1 Request flow for a single playback

```
┌─────────┐    1. POST /api/play/{tmdb_id}    ┌─────────────┐
│ Browser │ ───────────────────────────────▶ │   Backend   │
│         │                                   │  - rank src │
│         │ ◀─── {session_id, master_url} ─── │  - extract  │
│         │                                   │  - cache    │
│         │                                   └─────────────┘
│         │
│         │    2. GET /stream/{sid}/master.m3u8
│         │ ─────────────────────────────────▶
│         │                                          │
│         │                                   3. fetch upstream
│         │                                          │ vixcloud.co
│         │                                          ▼
│         │                                   4. rewrite URLs
│         │                                          │
│         │ ◀─── rewritten master.m3u8 ──────────────┘
│         │
│         │    5. GET /stream/{sid}/seg/720p/1.ts
│         │ ─────────────────────────────────▶
│         │                                   6. cache lookup → hit/miss
│         │                                          │
│         │                                   7. (miss) fetch upstream
│         │                                          │
│         │                                   8. (DRM?) decrypt
│         │                                          │
│         │                                   9. cache + return bytes
│         │ ◀─── segment bytes ─────────────────────┘
│         │
│         │    (continues for each segment...)
└─────────┘
```

### 8.2 Cache layers

| Layer | Location | Size | TTL | Eviction |
|---|---|---|---|---|
| RAM ring buffer | per-session in-memory dict | ~30 segments | session lifetime | FIFO when full |
| Disk LRU (segments) | `data/cache/segments/` | 30 GB (configurable) | 24 h | LRU by access time |
| Disk LRU (images) | `data/cache/posters,backdrops/` | 1.5 GB | 7 d | LRU |
| TMDB metadata | Postgres `catalog_items` | unlimited | per-collection TTL | manual refresh |
| Domain resolver | `data/domains_cache.json` | tiny | 6 h | ttl |
| Audio fingerprint | `data/cache/audio_fingerprints/` | 50 MB | indefinite | manual |
| Session state | in-memory dict | ephemeral | 4 h sliding | TTL |

### 8.3 Connection management

- **Single httpx AsyncClient** per outbound host (pool max 20 connections, keep-alive enabled).
- **HTTP/2** opportunistic: probed at first connection, downgrades to HTTP/1.1 if not supported.
- **curl_cffi sessions** retained per-domain — Cloudflare cookie + JA3 fingerprint cached.
- **No reconnects on transient errors** within a single session — let the upstream HTTP retry happen at the user-segment level.

### 8.4 Bandwidth and concurrency

Realistic load envelope on the Acer (8 GB RAM, dual-core Celeron):

| Concurrent streams | RAM use | CPU use | Verdict |
|---|---|---|---|
| 1 (you alone) | ~1.5 GB | ~5-15% | Fine |
| 2 (you + spouse different shows) | ~2 GB | ~15-25% | Fine |
| 3 (one DRM + two non-DRM) | ~3 GB | ~50-70% | Tight, OK |
| 4+ | ~4 GB | 90%+ | Choppy, avoid |

DRM streams cost more CPU because of segment decryption. Non-DRM is mostly I/O.

---

## 9. PWA & Cast Integration

### 9.1 PWA manifest

`static/manifest.webmanifest`:

```json
{
  "name": "Streamload",
  "short_name": "Streamload",
  "description": "La tua libreria personale.",
  "start_url": "/",
  "display": "standalone",
  "orientation": "any",
  "background_color": "#0a0a0a",
  "theme_color": "#0a0a0a",
  "icons": [
    {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
    {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    {"src": "/icons/icon-1024.png", "sizes": "1024x1024", "type": "image/png", "purpose": "any maskable"}
  ],
  "screenshots": [
    {"src": "/screenshots/home-mobile.png", "sizes": "750x1334", "type": "image/png", "platform": "narrow"},
    {"src": "/screenshots/home-desktop.png", "sizes": "1920x1080", "type": "image/png", "platform": "wide"}
  ],
  "shortcuts": [
    {"name": "Continua a guardare", "url": "/?row=continue-watching"},
    {"name": "Cerca", "url": "/search"}
  ]
}
```

### 9.2 Service Worker

Built via `vite-plugin-pwa`:
- **Precache** the SvelteKit app shell (HTML/CSS/JS bundles).
- **Runtime cache** for TMDB images (cache-first, max 200 entries, 7 d TTL).
- **Network-first** for API responses (so updates show fast).
- **No video segment caching in SW** — that's handled server-side; SW caching of MB-scale segments would balloon storage and complicate eviction.
- **Push notifications** out of scope for v1 (no use case yet).

### 9.3 Cast Sender SDK (Chromecast)

Lazy-loaded only when a Cast device is discoverable:

```javascript
// Lazy-load on first user interaction with cast button
async function loadCastSDK() {
    await loadScript('https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1');
    cast.framework.CastContext.getInstance().setOptions({
        receiverApplicationId: chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
        autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
    });
}
```

**Cast a stream**: when user taps Cast and selects a device, we send the master URL of the current session. The Cast device fetches it directly from our backend. **Important**: the Cast device must be on the same Tailscale network OR the Streamload backend must be reachable on its LAN — Chromecast does not natively run Tailscale. For v1: assume Cast devices on the same LAN as the backend (typical setup at home).

### 9.4 AirPlay

**Zero JavaScript** required. Vidstack (and any standard `<video>` element) exposes the AirPlay button automatically in Safari on iOS/macOS. The DRM streams are already decrypted server-side, so AirPlay receives plaintext HLS — works out of the box.

---

## 10. Development Environment

> **Note**: Production deployment is fully containerized — see **§17 (Containerization)** and **§18 (CI/CD)** for the canonical production setup. This section covers ONLY the developer machine (MacBook M4).

### 10.1 Dev: MacBook Air M4

Direct Python + SvelteKit dev servers, no Docker (faster iteration loop, hot reload everywhere):

- **Python**: 3.11+ via pyenv
- **Node**: 20+ via fnm or volta
- **Postgres**: 16 via Homebrew (`brew install postgresql@16`)
- **Tailscale**: installed for testing PWA on iPhone over LAN

```bash
# One-time setup
git clone <repo>
cd Streamload
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt requirements-dev.txt
cd web && npm install && cd ..
createdb streamload
alembic upgrade head

# Run (two terminals)
# Terminal 1 — backend with autoreload
granian --interface asgi --host 127.0.0.1 --port 8000 \
    --reload --loop uvloop streamload.api.app:app

# Terminal 2 — frontend with HMR
cd web && npm run dev   # serves on :5173, proxies /api → :8000
```

The dev frontend dev server proxies `/api` and `/stream` to the backend so a single browser tab on http://localhost:5173 sees a unified experience.

### 10.2 Production deployment summary

Production runs in Docker on the Acer (see §17 for the full Dockerfile, docker-compose.yml, and systemd unit that wraps `docker compose up`). Auto-update via Watchtower polling GHCR every 5 minutes — see §18.

### 10.3 Configuration

`config.json` extended:

```json
{
  "language": "it-IT",
  "auto_update": true,
  "tmdb": {
    "api_key": "REDACTED",
    "language": "it-IT",
    "region": "IT",
    "image_base_url": "https://image.tmdb.org/t/p/"
  },
  "auth": {
    "session_ttl_hours": 720,
    "passkey_rp_id": "streamload.<tailnet>.ts.net",
    "passkey_rp_name": "Streamload",
    "self_registration_open": true
  },
  "streaming": {
    "session_ttl_hours": 4,
    "ram_buffer_segments": 30,
    "disk_cache_size_gb": 30,
    "disk_cache_ttl_hours": 24,
    "prefetch_segments": 3
  },
  "ranker": {
    "weights": {
      "quality": 0.40,
      "latency": 0.20,
      "reliability": 0.20,
      "audio_match": 0.10,
      "subs_match": 0.10
    }
  },
  "catalog": {
    "refresh_concurrency": 8,
    "collections": [
      "trending-day",
      "popular-movies",
      "popular-tv",
      "anime-season",
      "top-rated-all-time",
      "genre-action",
      "genre-horror",
      "genre-scifi"
    ]
  },
  "drm": {
    "widevine": { "device_type": "ANDROID", "system_id": 22590, "security_level": 3, "host": "https://cdrm-project.com/remotecdm/widevine", "secret": "CDRM", "device_name": "public" },
    "playready": { "host": "https://cdrm-project.com/remotecdm/playready", "secret": "CDRM", "device_name": "public" }
  },
  "network": { "timeout": 30, "max_retry": 8, "verify_ssl": true, "proxy": null }
}
```

Secrets (TMDB API key, DB password) live in `.env` and `login.json` (gitignored).

### 10.4 Backup strategy

- **Postgres**: nightly `pg_dump` to `data/backups/streamload-YYYY-MM-DD.sql.gz`, last 14 days kept.
- **`secret/`**: manual offline backup of signing key (one-time).
- **`config.json`**: tracked in git (sans secrets).
- **Disk caches**: NOT backed up (regenerable).

---

## 11. Security Considerations

### 11.1 Threat model

We're a single-household Tailscale-only app. Threats considered:

| Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Tailscale ACL misconfig exposes app to public internet | Low | High | Bind to `100.x.x.x` (Tailscale IP) only; verify with `nmap` from external network |
| Family member abuses admin role | Low | Med | Self-registration creates `role='user'`; admin role manual promotion |
| Password brute force on login | Med | Med | argon2id + rate limit (10/IP/5min, 5/user/5min) |
| Session hijack via XSS | Low | High | HttpOnly cookies, strict CSP, no inline JS, no innerHTML for user content |
| CSRF | Low | Med | SameSite=Lax cookies, explicit CSRF token on DELETE/POST mutating ops |
| TMDB API key leak | Low | Low | Backend-only, never exposed to frontend, rotatable |
| DRM decrypt key leak | Low | High | Keys never exposed via API, ephemeral in session memory, rotated per session |
| Upstream service detects scraping → IP block | Med | Low | curl_cffi TLS impersonation + rate-limiting outbound + domain resolver fallback |
| Postgres compromise (privesc on the box) | Low | High | Unix-socket-only, system user, no remote listener |

### 11.2 Content Security Policy

```
default-src 'self';
script-src 'self' 'wasm-unsafe-eval' https://www.gstatic.com;  # gstatic for Cast SDK
img-src 'self' https://image.tmdb.org data: blob:;
media-src 'self' blob:;                                          # blob for hls.js
style-src 'self' 'unsafe-inline';                                # Tailwind generates inline (mitigated by Tailwind v4's hashing)
connect-src 'self' wss://streamload.<tailnet>.ts.net;           # WebSocket for progress
frame-ancestors 'none';                                          # never embeddable
```

### 11.3 Audit logging

`playback_events` table records every play_start, play_end, source_switch, error. Useful for:
- "Who watched what when" (legitimate household question)
- Debugging stuck/failed playback (forensics)
- Tracking source health over time (which Server N fails most)

No external telemetry. No analytics SDKs. No tracking.

---

## 12. Migration Plan from v1

### 12.1 What changes for the user

| v1 (CLI) | v2 (Web + CLI) |
|---|---|
| Curses TUI | SvelteKit web app + CLI preserved |
| Download to disk | Stream-only (no permanent files) |
| Single-user (no auth) | Multi-user with login |
| Search-first | Catalog browse + search |
| Manual mirror selection (implicit) | Auto-rank with override |

### 12.2 Code reuse

| v1 module | v2 fate |
|---|---|
| `streamload/services/*` | **100% reused.** Become async-friendly (existing sync methods wrapped via `asyncio.to_thread` initially, refactored to async progressively). |
| `streamload/player/*` | **100% reused.** Vixcloud, sweetpixel, etc. extractors unchanged. |
| `streamload/core/downloader/*` | **Repurposed.** The HLS segment fetcher logic becomes the streaming proxy fetcher; same HTTP code, different sink. |
| `streamload/core/manifest/*` | **100% reused.** m3u8/mpd parsers same. |
| `streamload/core/drm/*` | **100% reused.** CDM, key extraction unchanged. Used for server-side decrypt. |
| `streamload/core/post/*` | **Partially reused.** Subtitle conversion (vtt) very useful for browser. NFO generation no longer needed. Merge no longer needed. |
| `streamload/utils/domain_resolver/*` | **100% reused.** No changes needed. |
| `streamload/utils/http.py` | **Reused.** Already has async via httpx; ensure all v2 callers use `await http.get_async(...)`. |
| `streamload/utils/config.py` | **Extended.** Add `tmdb`, `auth`, `streaming`, `ranker`, `catalog` sections. |
| `streamload/cli/*` | **Preserved.** CLI continues to work for power users. |
| `streamload/models/*` | **Extended.** Add `User`, `WatchProgress`, `CatalogItem`, etc. as SQLAlchemy models. Existing dataclasses (`MediaEntry`, `StreamBundle`) coexist. |
| `streamload/api/*` | **New.** FastAPI app, routes, streaming proxy, auth, catalog endpoints. |
| `streamload/catalog/*` | **New.** TMDB client, ingest, ranker. |
| `streamload/auth/*` | **New.** Passwords, passkeys, sessions. |
| `streamload/db/*` | **New.** Alembic migrations, SQLAlchemy session factory. |
| `web/` | **New.** SvelteKit project. |

### 12.3 Migration phases (pre-implementation plan)

The implementation plan (next step) will break this down further. Macro phases:

1. **Foundation**: Postgres setup, Alembic migrations, FastAPI skeleton, async refactor of HttpClient.
2. **Auth + Email**: users, sessions, passkeys, email verification (Resend), password reset, login UI.
3. **Catalog**: TMDB client, ingestion worker, source ranker.
4. **Streaming proxy**: HLS rewrite + segment proxy + cache (non-DRM first).
5. **DRM streaming**: server-side decrypt + remux pipeline.
6. **Frontend skeleton**: SvelteKit setup, layout, navigation, visual design system.
7. **Pages**: home, library, detail, search.
8. **Player**: Vidstack integration + custom skin + watch progress + auto-play next.
9. **PWA & Cast**: manifest, SW, Cast SDK.
10. **Skip intro/outro**: audio fingerprinting + markers + UI.
11. **Polish**: animations, error states, settings page, admin dashboard.
12. **Containerization**: multi-stage Dockerfile, docker-compose, Tailscale wiring.
13. **CI/CD**: GitHub Actions pipeline, GHCR publishing, Watchtower setup, rollback procedure.
14. **Production deployment**: first-time Acer bootstrap, ops runbook, backup strategy.

---

## 13. Testing Strategy

### 13.1 Backend

- **Unit tests** (pytest) for: ranker scoring, catalog matching, M3U8 rewrite, intro fingerprint, auth flows.
- **Integration tests** (pytest + httpx test client) for: full playback session lifecycle (mocked upstream), auth flows end-to-end, catalog ingestion (mocked TMDB).
- **Real-network smoke tests** (pytest with `@pytest.mark.network`, opt-in via env): probe SC, AnimeUnity, etc. for catalog ingestion correctness. Run nightly via GitHub Action (already planned in v1 backlog).

Target: 80%+ line coverage on new modules. Existing v1 modules keep their current coverage.

### 13.2 Frontend

- **Unit tests** (Vitest) for: stores, derived state, utility functions.
- **Component tests** (Vitest + Testing Library Svelte) for: PosterCard, Row, Player skin overlays.
- **E2E tests** (Playwright, headless): login flow, browse home, click title, play a (mocked) stream, verify progress sync.
- **Visual regression** (Playwright + Argos or built-in screenshots): home page, player UI, login form. Catches CSS regressions across our 4 breakpoints.

### 13.3 Manual test matrix per release

| Device | Browser | Test |
|---|---|---|
| MacBook | Safari 17+ | Login, home, play, AirPlay |
| MacBook | Chrome | Login, home, play, Cast |
| iPhone | Safari iOS 17+ | PWA install, login, home, play, AirPlay |
| iPad | Safari iOS 17+ | PWA install, browse, play landscape |
| Android | Chrome | PWA install, login, play, Cast |
| Acer (prod) | (server, not browser) | systemd start, full ingest run, 3 concurrent streams |

---

## 14. Risks & Open Questions

### 14.1 Technical risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Acer hardware too weak for 2 DRM streams concurrently | Med | Med | Profile early; if real, document limit; offer "single-stream mode" config |
| Audio fingerprinting fails on series with frequent intro changes | Med | Low | Low confidence threshold → no marker shown; user falls back to manual seek |
| TMDB rate limits during ingest | Low | Low | Existing TMDB free tier is generous (40 req/sec); we batch; ingestion is hourly not real-time |
| Cast SDK changes break Chromecast | Low | Low | Lazy-load + feature-detect; fallback to mirror via AirPlay |
| Vidstack v3 → v4 breaking changes during dev | Low | Low | Pin major version; upgrade in dedicated cycles |
| Passkey support inconsistent across browsers | Low | Low | Always offer password as fallback; passkey is enhancement |

### 14.2 Open questions for spec review

These are points where the spec proposes a default but the user might want different:

1. **Self-registration "open" vs "invite-only"**: chosen open per Q11.a, but if family changes, can switch to invite via admin promotion.
2. **Watch progress sync interval**: 15s heartbeat. Tunable.
3. **Disk cache size**: 30 GB default. May be too aggressive if Acer SSD is small. Configurable.
4. **Genre rows on home**: chose Action / Horror / Sci-Fi as starter set. User can add/remove via collections config.
5. **Content rating filter (parental)**: not in spec. If kids will use it, add a per-user "max content rating" filter (TMDB has this data).

### 14.3 Out-of-scope items deferred to post-v2

- IMDb / Letterboxd / Trakt sync
- Real-time co-watch
- Audio extraction for music-video / podcast use case
- Live TV channels
- Native iOS / Android apps
- Recommendations engine ML-based
- Multi-server deployment

---

## 15. Success Criteria for v2 Release

The v2 is "done" when:

**Auth & users**
- [ ] Self-registration works; first user becomes admin; subsequent users are role='user'.
- [ ] Email verification email arrives within 30s; clicking the link verifies the account.
- [ ] Unverified users can log in but cannot start playback.
- [ ] Password reset email arrives + token-based reset flow works end-to-end.
- [ ] Login works with both password and passkey.

**Catalog & playback**
- [ ] Home displays at least 5 collection rows populated by reverse-lookup.
- [ ] Title detail page shows poster, plot, ranked sources (labeled "Server N").
- [ ] Click "Play" on a non-DRM title → video starts within 3 seconds.
- [ ] Click "Play" on a DRM title (RaiPlay) → video starts within 5 seconds.
- [ ] Watch progress persists across reload + cross-source resume.
- [ ] Auto-play next episode triggers in TV series.
- [ ] Italian audio + Italian subs auto-selected when available.
- [ ] Skip intro button appears in episodes 3+ of a series after fingerprinting episodes 1-2.

**Devices**
- [ ] PWA installs on iOS Safari + Android Chrome.
- [ ] Cast to Chromecast works on Chrome desktop.
- [ ] AirPlay to Apple TV works on Safari iOS.

**Production deployment**
- [ ] Docker image builds in <8 min on GitHub Actions (amd64 + arm64).
- [ ] Image size <300 MB compressed.
- [ ] `docker compose up` on the Acer brings up the full stack cleanly.
- [ ] Healthcheck reports green within 60s of container start.
- [ ] All routes work on Acer hardware with 1 user, no perceptible lag.
- [ ] Watchtower successfully detects + applies a deliberate version bump in <10 min from git push.
- [ ] Active streams reconnect cleanly after auto-update (player retries HLS segments).
- [ ] Rollback to previous tag works via `docker compose pull <prev-tag> && docker compose up`.

**Quality**
- [ ] All 122+ existing tests still pass + new test coverage >= 80% on new modules.
- [ ] No console errors in production browser.
- [ ] Backend startup time on Acer <15 s.
- [ ] `/api/version` returns correct git SHA + tag.

---

---

## 16. Email Service

### 16.1 Use cases

1. **Registration confirmation**: when a user signs up, server generates a token, sends `https://streamload.<tailnet>.ts.net/verify?token=...`. Account is `unverified` (read-only access to its own data, no playback) until verified.
2. **Password reset**: user requests reset via username/email. Server emails `https://streamload.<tailnet>.ts.net/reset?token=...` (token TTL: 1h, single-use).
3. **Passkey lost / lockout** (rare): admin manually reissues invite or password reset email.

For v1 we deliberately do **not** add: change-of-email confirmation, login alerts, marketing, or notification emails.

### 16.2 Provider choice: Resend

**Why Resend**: best DX (modern API), generous free tier (3000/month, 100/day), excellent deliverability out-of-box with their sender domain. Time-to-first-email: ~3 minutes from signup.

**Setup**:
1. Sign up at https://resend.com (free)
2. Verify a domain you own (e.g., `streamload.alfanowski.dev`) OR use the resend.dev shared sender for v1 (works but emails come from `noreply@resend.dev`)
3. Get API key, add to `login.json`:
   ```json
   { "RESEND": { "api_key": "re_xxxxxxxxxxxxxxx", "from_address": "noreply@yourdomain.com" } }
   ```

**Library**: official `resend` Python SDK (sync, but we wrap with `asyncio.to_thread`).

### 16.3 Token model

```sql
CREATE TABLE email_tokens (
    token_hash      BYTEA PRIMARY KEY,                 -- sha256(opaque_token)
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose         TEXT NOT NULL,                     -- 'verify_email' | 'reset_password'
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ,                       -- NULL = unused, NOT NULL = used
    CHECK (purpose IN ('verify_email', 'reset_password'))
);

CREATE INDEX idx_email_tokens_user ON email_tokens(user_id);
```

Token TTL:
- `verify_email`: 24h, can be re-issued (replaces previous unused tokens for same user)
- `reset_password`: 1h, single-use, invalidates all sessions on consumption

### 16.4 User schema additions

```sql
ALTER TABLE users
    ADD COLUMN email_verified_at TIMESTAMPTZ,
    ADD COLUMN email_required BOOLEAN NOT NULL DEFAULT TRUE;
```

`email_required = TRUE` (default) blocks playback until verified. Admin can flip to `FALSE` to bypass for special accounts (e.g., a "guest" account for the apartment guest WiFi during a viewing party).

### 16.5 Email templates

Two templates, plain HTML (no fancy CSS — email clients are hostile). Identity:

- **Brand color**: `#d4a574` (matches the app's amber accent)
- **Subject lines**:
  - Verify: "Conferma il tuo account Streamload"
  - Reset: "Reimposta la tua password"
- **Sender name**: `Streamload`
- **Sender address**: `noreply@<your-domain>` after domain verification, else `noreply@resend.dev`
- **Footer**: tiny disclaimer, no unsubscribe (transactional only)

### 16.6 Rate limiting

- Verify-email re-sends: max 3 per user per 24h
- Password resets: max 5 per user per 24h, max 20 per IP per 24h
- Anti-enumeration: respond identically whether email exists or not ("Se esiste un account, riceverai un'email a breve")

---

## 17. Containerization (Production Only)

### 17.1 Image strategy

Production deployments run in Docker on the Acer. **Development on the MacBook M4 does NOT use Docker** — direct Python + SvelteKit dev servers for fast iteration.

**Final image target size**: ~250 MB compressed (multi-stage build, slim base, no build tooling in runtime).

### 17.2 Multi-stage Dockerfile

```dockerfile
# syntax=docker/dockerfile:1.7

# ============================================================
# Stage 1: Frontend builder
# ============================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --frozen-lockfile

COPY web/ ./
RUN npm run build
# Output: /app/web/build (SvelteKit static adapter)

# ============================================================
# Stage 2: Backend builder (pre-compile wheels for amd64+arm64)
# ============================================================
FROM python:3.11-slim AS backend-builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-prod.txt ./
RUN pip install --user --no-cache-dir -r requirements-prod.txt

# ============================================================
# Stage 3: Runtime
# ============================================================
FROM python:3.11-slim AS runtime

# Minimal runtime deps: ffmpeg for thumbnail extraction & audio fingerprint
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libpq5 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -m -u 1000 streamload
WORKDIR /app

# Copy backend wheels and Python deps
COPY --from=backend-builder --chown=streamload:streamload /root/.local /home/streamload/.local
ENV PATH="/home/streamload/.local/bin:$PATH"

# Copy backend source
COPY --chown=streamload:streamload streamload/ ./streamload/
COPY --chown=streamload:streamload pyproject.toml ./
COPY --chown=streamload:streamload alembic.ini ./
COPY --chown=streamload:streamload migrations/ ./migrations/

# Copy frontend build into backend's static dir
COPY --from=frontend-builder --chown=streamload:streamload /app/web/build ./streamload/api/static/

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/health').raise_for_status()" || exit 1

USER streamload

EXPOSE 8000
ENV PYTHONUNBUFFERED=1

CMD ["granian", "--interface", "asgi", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--loop", "uvloop", \
     "streamload.api.app:app"]
```

### 17.3 docker-compose.yml (production)

```yaml
version: "3.8"

services:
  streamload:
    image: ghcr.io/alfanowski/streamload:${STREAMLOAD_VERSION:-latest}
    container_name: streamload
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    env_file:
      - .env
    volumes:
      - ./data:/app/data
      - ./secret:/app/secret:ro
      - ./config.json:/app/config.json:ro
      - ./domains.json:/app/domains.json:ro
      - ./domains.json.sig:/app/domains.json.sig:ro
    ports:
      - "127.0.0.1:8000:8000"  # bind to localhost; Tailscale forwards via TS Funnel or sidecar
    # OR for Tailscale interface only:
    # ports:
    #   - "100.x.x.x:8000:8000"  # the Tailscale IP of this host
    networks:
      - streamload-net

  postgres:
    image: postgres:16-alpine
    container_name: streamload-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: streamload
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
      POSTGRES_DB: streamload
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U streamload"]
      interval: 5s
      timeout: 3s
      retries: 5
    secrets:
      - postgres_password
    networks:
      - streamload-net

  watchtower:
    image: containrrr/watchtower:latest
    container_name: streamload-watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      WATCHTOWER_POLL_INTERVAL: 300        # 5 min
      WATCHTOWER_CLEANUP: "true"            # remove old images
      WATCHTOWER_INCLUDE_RESTARTING: "true"
      WATCHTOWER_LABEL_ENABLE: "true"        # only update containers with com.centurylinklabs.watchtower.enable=true
    labels:
      com.centurylinklabs.watchtower.enable: "false"   # don't update watchtower itself

volumes:
  postgres-data:

networks:
  streamload-net:
    driver: bridge

secrets:
  postgres_password:
    file: ./secret/postgres-password.txt
```

### 17.4 Tailscale integration in container

Two viable patterns:

**Pattern A — Host network mode** (simplest):
- Container runs with `network_mode: host`
- Listens on the host's Tailscale interface (`100.x.x.x:8000`)
- Tailscale runs on host (already installed)

**Pattern B — Tailscale sidecar** (cleaner separation):
- A `tailscale/tailscale` container provides the network namespace
- The streamload container shares network with it: `network_mode: "service:tailscale"`
- The Tailscale container has its own auth key

**Recommendation**: Pattern A for simplicity. Tailscale on the host, container binds to the Tailscale IP via a small startup script that resolves it.

### 17.5 Migrations on container start

The container's entrypoint runs:
```
1. alembic upgrade head    (idempotent; no-op if already at head)
2. exec granian ...         (replaces shell PID, signal-safe)
```

Implemented in `entrypoint.sh`:
```bash
#!/bin/sh
set -e
echo "Running database migrations..."
alembic upgrade head
echo "Starting Streamload..."
exec granian --interface asgi --host 0.0.0.0 --port 8000 \
    --workers 1 --loop uvloop streamload.api.app:app
```

### 17.6 Image size optimization checklist

- [ ] Multi-stage build (no build tools in runtime)
- [ ] `python:3.11-slim` base (not `python:3.11`, ~50% smaller)
- [ ] `--no-cache-dir` on pip install
- [ ] Combine RUN commands to reduce layers
- [ ] Remove `apt` lists after install
- [ ] No node_modules in runtime image (only the built static)
- [ ] No `__pycache__` (set `PYTHONDONTWRITEBYTECODE=1`)
- [ ] Use `.dockerignore` to exclude tests/, docs/, .git/, venv/, etc.

Target: **<300 MB compressed**, **<800 MB on disk after pull**. Acceptable on a 8 GB RAM Acer.

---

## 18. CI/CD & Auto-Update

### 18.1 Pipeline overview

```
┌─────────────────────────────────────────────────────────────┐
│   git push to main / git tag vX.Y.Z                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
            ┌────────────────────────────┐
            │   GitHub Actions Pipeline   │
            │                             │
            │   1. test (pytest)          │
            │   2. lint (ruff, eslint)    │
            │   3. build frontend (vite)  │
            │   4. build Docker image     │
            │      (linux/amd64+arm64)    │
            │   5. push to ghcr.io        │
            │   6. (on tag) GitHub Release│
            └────────────────┬────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │   ghcr.io/alfanowski/  │
                  │   streamload:latest    │
                  │   streamload:v0.x.y    │
                  │   streamload:vX.Y      │
                  │   streamload:vX        │
                  └──────────┬───────────┘
                             │ (polled every 5 min)
                             ▼
                  ┌──────────────────────┐
                  │   Watchtower (Acer)  │
                  │                       │
                  │  - detects new digest │
                  │  - docker pull        │
                  │  - docker compose up  │
                  │    --no-deps -d       │
                  │    streamload         │
                  │  - cleanup old image  │
                  └───────────────────────┘
```

### 18.2 Workflow file

`.github/workflows/build-and-publish.yml`:

```yaml
name: Build & Publish

on:
  push:
    branches: [main]
    tags: ['v*.*.*']
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  test-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11', cache: 'pip' }
      - run: pip install -r requirements.txt
      - run: pytest --cov=streamload --cov-report=term

  test-frontend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: web } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20', cache: 'npm', cache-dependency-path: web/package-lock.json }
      - run: npm ci
      - run: npm run lint
      - run: npm run check          # svelte-check
      - run: npm run test:unit      # vitest

  build-and-push:
    needs: [test-backend, test-frontend]
    if: github.event_name == 'push' || startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=raw,value=latest,enable={{is_default_branch}}
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=semver,pattern={{major}}
            type=sha,prefix=,format=short

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  release:
    needs: build-and-push
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: orhun/git-cliff-action@v2
        with: { args: --latest --strip header }
        id: changelog
      - uses: softprops/action-gh-release@v2
        with:
          body: ${{ steps.changelog.outputs.content }}
          token: ${{ secrets.GITHUB_TOKEN }}
```

### 18.3 Versioning convention

**Semantic Versioning** (`vMAJOR.MINOR.PATCH`):
- **MAJOR**: breaking schema changes that require manual migration steps (rare)
- **MINOR**: new features, backward-compatible (typical release)
- **PATCH**: bug fixes only

Tags trigger:
- `v0.5.3` → image tags `:v0.5.3`, `:v0.5`, `:v0`, `:latest` (since main branch only)
- Watchtower can be configured to follow `:v0` (auto-updates patches/minors but stops at v1) for stability

### 18.4 Watchtower configuration

By default, Watchtower polls every 5 minutes and updates any container with the label enabled. Streamload's container in `docker-compose.yml` has:

```yaml
labels:
  com.centurylinklabs.watchtower.enable: "true"
  # Optional: pin to a specific tag stream
  # com.centurylinklabs.watchtower.depends-on: postgres
```

**Update strategy**:
- Streamload container: ✅ auto-update from `:latest`
- Postgres container: ❌ never auto-update (data risk; we'll do manual pg_upgrade on major version bumps)
- Watchtower itself: ❌ never auto-update (avoid race conditions)

### 18.5 Rollback strategy

If an update breaks production:

```bash
# On the Acer:
ssh acer
cd /opt/streamload
docker compose pull ghcr.io/alfanowski/streamload:v0.5.2  # the previous good version
# Edit docker-compose.yml or set env var:
STREAMLOAD_VERSION=v0.5.2 docker compose up -d streamload
```

Backup of working `:latest` digest is kept by Watchtower for one cycle; in practice, downgrade by explicit tag.

### 18.6 Rolling deploy considerations

Single-instance deployment so there's no rolling update. Watchtower does:
1. `docker pull` (downloads while old container runs)
2. `docker stop streamload` (graceful shutdown via SIGTERM, 10s grace period)
3. `docker rm streamload`
4. `docker run` with new image
5. Healthcheck waits for app to be ready

**Total downtime per update**: 5-15 seconds typically. Active streams will reconnect (HLS is segment-based; the player retries). Acceptable trade-off for a personal app.

### 18.7 Deployment monitoring

- Backend exposes `/api/version` returning `{git_sha, version, build_date}`.
- Frontend footer shows version + git SHA (clickable to GitHub commit).
- Optional Slack/Discord webhook from Watchtower on update events (Watchtower supports out-of-box via `WATCHTOWER_NOTIFICATION_*` env vars).

### 18.8 GitHub Container Registry (GHCR) — why

| Registry | Cost | Free tier | Verdict |
|---|---|---|---|
| **GHCR** | Free for public repos | Unlimited storage + bandwidth | ⭐ Best for our scope |
| Docker Hub | Free tier 100 pulls/6h anon | Limited | Throttled |
| AWS ECR | Pay-per-GB | $0.10/GB/month | Overkill |
| Self-hosted Harbor | Free | Self-managed | Overhead |

GHCR integrates seamlessly with GitHub Actions (uses `GITHUB_TOKEN`, no extra secret).

### 18.9 First-time deployment on the Acer

One-time bootstrap:

```bash
ssh alfanowski@acer
sudo mkdir -p /opt/streamload && sudo chown $USER /opt/streamload && cd /opt/streamload
git clone --depth=1 https://github.com/alfanowski/Streamload.git . --branch main
cp config.json.example config.json    # edit
cp .env.example .env                   # edit (TMDB key, RESEND key, POSTGRES_PASSWORD, etc.)
mkdir -p secret data
# transfer secret/domains_signing_key.pem from offline backup
docker compose pull
docker compose up -d
docker compose logs -f streamload     # watch first migration + first launch
```

After this, all updates are automatic via Watchtower.

---

**End of design document.**

*Next step: write the implementation plan based on this spec.*
