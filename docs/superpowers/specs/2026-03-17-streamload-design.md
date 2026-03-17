# Streamload - Design Specification

**Date:** 2026-03-17
**Status:** Draft
**Version:** 1.2

## Overview

Streamload is a professional, cross-platform, CLI-only Python tool for downloading video content from 15 streaming services. It replaces VibraVid with a clean, enterprise-grade architecture built on a layered module system with a service plugin registry.

**Entry point:** `python3 streamload.py`
**No GUI, no web interface** - pure CLI with rich terminal UI.

## Goals

- Professional, scalable architecture with strict layer separation
- Cross-platform (macOS, Linux, Windows) with zero GUI dependencies
- Plugin registry for streaming services (auto-discovery, common interface)
- Modern interactive CLI with alternate screen buffer
- Internationalization (Italian/English) with system language auto-detect
- Type-safe configuration with validation and sensible defaults
- Structured error handling - never crash silently, never swallow errors

## Non-Goals

- Web GUI (removed - was Django in VibraVid)
- Hook system (removed)
- Cloud vault / Supabase (removed - local SQLite vault only)
- PyPI distribution (user clones repo, installs requirements, runs script)
- Third-party plugin support (services are internal plugins only)

---

## Architecture

### Layer Diagram

```
streamload.py (entry point)
│
├── cli/          UI layer - terminal rendering, user interaction
│   ├── app.py              Main orchestrator
│   ├── terminal.py         Alternate screen buffer management
│   ├── ui/                 Reusable UI components (tables, selectors, progress)
│   └── i18n/               Internationalization (it, en)
│
├── core/         Logic layer - zero UI, zero print, event-driven
│   ├── downloader/         Download engines (HLS, DASH, MP4)
│   ├── drm/                DRM decryption (Widevine, PlayReady)
│   ├── manifest/           Stream manifest parsing (m3u8, MPD)
│   ├── post/               Post-processing (FFmpeg merge, subtitles, NFO)
│   └── vault/              Local SQLite DRM key cache
│
├── services/     Service layer - plugin registry + 15 service implementations
│   ├── __init__.py         ServiceRegistry (auto-discovery)
│   ├── base.py             ServiceBase (abstract interface)
│   └── <service>/          One directory per service
│
├── models/       Shared data models (dataclasses with type hints)
│
└── utils/        Cross-cutting utilities (HTTP, config, logging, system checks)
```

### Key Architectural Principle

**Core never touches the terminal.** The core layer communicates with the CLI through an event callback system. The core emits events (progress, errors, selection requests), and the CLI handles rendering. This makes the core fully testable and UI-independent.

---

## Project Structure

```
Streamload/
├── streamload.py                  # Entry point: python3 streamload.py
├── requirements.txt
├── config.json                    # User configuration
├── login.json                     # Service credentials + TMDB API key
│
├── streamload/                    # Main package
│   ├── __init__.py
│   ├── version.py
│   │
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── app.py                 # Main CLI orchestrator
│   │   ├── terminal.py            # Alternate screen buffer manager
│   │   ├── ui/
│   │   │   ├── __init__.py
│   │   │   ├── tables.py          # Search result tables
│   │   │   ├── selector.py        # Interactive track/episode selection
│   │   │   ├── progress.py        # Download progress bars
│   │   │   └── prompts.py         # User input, confirmations
│   │   └── i18n/
│   │       ├── __init__.py        # I18n class, system language detection
│   │       ├── it.py              # Italian strings
│   │       └── en.py              # English strings
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── events.py              # Event dataclasses + EventCallbacks interface
│   │   ├── downloader/
│   │   │   ├── __init__.py
│   │   │   ├── base.py            # BaseDownloader (abstract)
│   │   │   ├── hls.py             # HLS/m3u8 downloader
│   │   │   ├── dash.py            # DASH/MPD downloader
│   │   │   ├── mp4.py             # Direct MP4 downloader
│   │   │   └── manager.py         # DownloadManager (concurrency, queue)
│   │   ├── drm/
│   │   │   ├── __init__.py
│   │   │   ├── manager.py         # DRM orchestrator
│   │   │   ├── widevine.py        # Widevine L3 CDM
│   │   │   └── playready.py       # PlayReady CDM
│   │   ├── manifest/
│   │   │   ├── __init__.py
│   │   │   ├── m3u8.py            # HLS manifest parser
│   │   │   ├── mpd.py             # DASH manifest parser
│   │   │   └── stream.py          # Stream variant selection
│   │   ├── post/
│   │   │   ├── __init__.py
│   │   │   ├── merge.py           # FFmpeg merge operations
│   │   │   ├── metadata.py        # NFO file generation
│   │   │   └── subtitles.py       # Subtitle format conversion
│   │   └── vault/
│   │       ├── __init__.py
│   │       └── local.py           # SQLite DRM key vault
│   │
│   ├── services/
│   │   ├── __init__.py            # ServiceRegistry class
│   │   ├── base.py                # ServiceBase abstract class
│   │   ├── animeunity/
│   │   │   ├── __init__.py
│   │   │   ├── scraper.py
│   │   │   └── extractor.py
│   │   ├── animeworld/
│   │   ├── crunchyroll/
│   │   ├── discovery/
│   │   ├── dmax/
│   │   ├── foodnetwork/
│   │   ├── guardaserie/
│   │   ├── homegardentv/
│   │   ├── mediasetinfinity/
│   │   ├── mostraguarda/
│   │   ├── nove/
│   │   ├── raiplay/
│   │   ├── realtime/
│   │   ├── streamingcommunity/
│   │   └── tubitv/
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── media.py               # Film, Serie, Season, Episode
│   │   ├── stream.py              # VideoTrack, AudioTrack, SubtitleTrack
│   │   └── config.py              # Typed configuration dataclasses
│   │
│   └── utils/
│       ├── __init__.py
│       ├── http.py                # HTTP client (httpx + curl_cffi)
│       ├── config.py              # ConfigManager (load, validate, defaults)
│       ├── logger.py              # Structured file logging with rotation
│       ├── system.py              # OS detection, FFmpeg check, dependency validation
│       ├── tmdb.py                # TMDB API client
│       └── updater.py             # Auto-update from GitHub
```

---

## Service Plugin Registry

### ServiceBase Interface

Every streaming service implements this abstract interface:

```python
class ServiceBase(ABC):
    name: str                    # "StreamingCommunity"
    short_name: str              # "sc"
    domains: list[str]           # ["streamingcommunity.xxx"]
    category: ServiceCategory    # FILM, SERIE, ANIME, FILM_SERIE
    language: str                # "it", "en"
    requires_login: bool

    @abstractmethod
    def search(self, query: str) -> list[MediaEntry]: ...

    @abstractmethod
    def get_seasons(self, entry: MediaEntry) -> list[Season]: ...

    @abstractmethod
    def get_episodes(self, season: Season) -> list[Episode]: ...

    @abstractmethod
    def get_streams(self, item: Episode | MediaEntry) -> StreamBundle: ...
```

### ServiceRegistry

```python
class ServiceRegistry:
    _services: dict[str, type[ServiceBase]] = {}

    @classmethod
    def register(cls, service_class):
        """Decorator: @ServiceRegistry.register"""
        cls._services[service_class.short_name] = service_class
        return service_class

    @classmethod
    def get_all(cls) -> list[type[ServiceBase]]: ...

    @classmethod
    def get_by_category(cls, cat: ServiceCategory) -> list[type[ServiceBase]]: ...

    @classmethod
    def instantiate_all(cls, http_client, config) -> dict[str, ServiceBase]:
        """Instantiate all registered service classes. Called once at startup."""

    @classmethod
    def search_all(cls, query: str, instances: dict[str, ServiceBase]) -> list[SearchResult]: ...
```

### Adding a New Service

1. Create directory `streamload/services/<name>/`
2. Implement `ServiceBase` in `__init__.py`
3. Add `@ServiceRegistry.register` decorator
4. Done - the registry auto-discovers it on startup

### Supported Services (15)

| Service | Category | Language |
|---------|----------|----------|
| StreamingCommunity | Film + Serie | IT |
| RaiPlay | Film + Serie | IT |
| Mediaset Infinity | Film + Serie | IT |
| Discovery | Film + Serie | IT |
| TubiTV | Serie | EN |
| Crunchyroll | Anime | Multi |
| AnimeUnity | Anime | IT |
| AnimeWorld | Anime | IT |
| GuardaSerie | Serie | IT |
| DMAX | Serie | IT |
| Food Network | Serie | IT |
| Nove | Serie | IT |
| HomeGardenTV | Serie | IT |
| Real Time | Serie | IT |
| MostraGuarda | Film | IT |

---

## Core ↔ CLI Communication

### Event System

The core never prints or reads input. It communicates through typed event callbacks:

The core emits typed events (see Data Models section for full definitions). The CLI consumes them via the `EventCallbacks` interface:

```python
class EventCallbacks(ABC):
    def on_track_selection(self, event: TrackSelection) -> SelectedTracks: ...
    def on_progress(self, event: DownloadProgress): ...
    def on_complete(self, event: DownloadComplete): ...
    def on_error(self, event: ErrorEvent): ...
    def on_warning(self, event: WarningEvent): ...
```

The CLI implements `EventCallbacks` with rich terminal rendering. Tests implement it with mock callbacks.

---

## Configuration

### Typed Configuration Model

```python
@dataclass
class AppConfig:
    language: str = "auto"            # auto | it | en
    preferred_audio: str = "auto"     # follows language when auto
    preferred_subtitle: str = "auto"  # follows language when auto
    auto_update: bool = True
    output: OutputConfig              # paths, formats, extension
    download: DownloadConfig          # threads, retries, concurrency, speed limit
    process: ProcessConfig            # GPU, NFO, subtitle format, merge options
    network: NetworkConfig            # timeout, retries, SSL, proxy
    drm: DRMConfig                    # Widevine/PlayReady server config
```

### Config Sections

**OutputConfig:**
- `root_path` (default: "Video")
- `movie_folder`, `serie_folder`, `anime_folder`
- `movie_format`, `episode_format` (template strings)
- `extension` (mkv | mp4)

**DownloadConfig:**
- `thread_count` (default: 8, range: 1-32)
- `retry_count` (default: 25)
- `max_concurrent` (default: 3) - parallel downloads
- `max_speed` (optional, e.g. "30MB")
- `cleanup_tmp` (default: true)

**ProcessConfig:**
- `use_gpu` (default: false)
- `generate_nfo` (default: false)
- `merge_audio`, `merge_subtitle` (default: true)
- `subtitle_format` (auto | srt | vtt | ass)

**NetworkConfig:**
- `timeout` (default: 30s)
- `max_retry` (default: 8)
- `verify_ssl` (default: true)
- `proxy` (optional, "http://host:port")

### Validation

Every field has a type and constraints. Invalid values trigger a warning log and fallback to the default. The application never crashes from bad configuration.

---

## Internationalization (i18n)

### System Language Auto-Detection

On startup, `locale.getlocale()` (or `locale.getdefaultlocale()` as fallback) detects the OS language:
- `it_IT` → Italian interface + `preferred_audio="ita|it"` + `preferred_subtitle="ita|it"`
- `en_US` (or any non-Italian) → English interface + `preferred_audio="eng|en"` + `preferred_subtitle="eng|en"`

Overridable in `config.json` via `language`, `preferred_audio`, `preferred_subtitle`.

### String Management

All user-visible text goes through `i18n.t(key, **params)`. Adding a language = creating a new string file. No hardcoded strings in CLI code.

---

## Terminal Management

### Alternate Screen Buffer

Streamload uses the terminal's alternate screen buffer (ANSI escape `\033[?1049h`):

- **On start:** enters alternate screen → clean workspace, original terminal preserved
- **On exit:** leaves alternate screen → user sees their previous terminal output intact
- **On crash/Ctrl+C:** `__exit__` handler ensures the terminal is always restored

Implemented via `TerminalManager` context manager wrapping the entire application lifecycle.

---

## User Flow

```
python3 streamload.py
│
├─ 1. STARTUP
│  ├─ Enter alternate screen buffer
│  ├─ Load & validate config.json + login.json
│  ├─ Detect system language → set i18n + audio/subtitle preferences
│  ├─ Check dependencies (FFmpeg, FFprobe) with helpful install instructions
│  ├─ Check for updates (non-blocking, 3s timeout)
│  └─ Load ServiceRegistry (auto-discover all services)
│
├─ 2. MAIN MENU
│  ├─ [1] Global search (search across all services)
│  ├─ [2] Select service (pick a specific one)
│  ├─ [3] Settings
│  └─ [4] Exit
│
├─ 3. SEARCH
│  ├─ User types query
│  ├─ If global: parallel search across all services
│  ├─ Results displayed in sorted table (name, year, type, service, language)
│  ├─ TMDB enrichment (year, genre)
│  └─ User selects a result
│
├─ 4. CONTENT SELECTION
│  ├─ If FILM → go to step 5
│  └─ If SERIES:
│     ├─ Show seasons → user selects
│     ├─ Show episodes with interactive selection:
│     │  ├─ Toggle individual (space)
│     │  ├─ Select all (shortcut)
│     │  ├─ Range ("3-7")
│     │  └─ Confirm (Enter)
│     └─ Go to step 5 for each selected episode
│
├─ 5. TRACK SELECTION (per content)
│  ├─ Show available video tracks (resolution, codec, bitrate)
│  ├─ Show available audio tracks (language, codec, channels)
│  ├─ Show available subtitles (language, format)
│  ├─ Pre-selected based on system language / config
│  └─ User modifies interactively → confirm
│
├─ 6. DOWNLOAD
│  ├─ DRM: request keys (local vault → external server)
│  ├─ Download segments with threading + progress bars
│  ├─ Multiple downloads: parallel progress bars (max 3 concurrent)
│  ├─ Error handling + automatic retry
│  └─ Per download completion:
│     ├─ FFmpeg merge (video + audio + subtitles)
│     ├─ Generate NFO (if enabled)
│     └─ Cleanup temp files
│
├─ 7. COMPLETION
│  ├─ Summary: what was downloaded, where, file sizes
│  └─ Return to main menu (loop)
│
└─ 8. EXIT
   ├─ Cleanup resources
   └─ Leave alternate screen → terminal restored
```

---

## Error Handling

### Exception Hierarchy

```
StreamloadError (base)
├── NetworkError       - timeout, DNS, connection failures
├── ServiceError       - service responded with error or changed structure
├── DRMError           - key not found, CDM unavailable
├── MergeError         - FFmpeg failed
└── ConfigError        - invalid or corrupted configuration
```

### Error Strategy by Level

| Level | Behavior |
|-------|----------|
| Failed segment | Auto-retry up to `retry_count`, then skip + warn |
| Failed track | Warn user, continue with other tracks |
| Failed download | Show clear error, ask whether to continue with remaining |
| Unreachable service | Skip in global search, warn |
| FFmpeg failure | Show error, keep raw downloaded files |
| Invalid config | Warning + fallback to default, never crash |

### Logging

Structured logging to file (`streamload.log`) with automatic rotation. The terminal only shows what the CLI layer decides to display. Debug-level details are always available in the log file for troubleshooting.

---

## Concurrent Downloads

- **Max concurrent downloads:** configurable (default: 3)
- **Threads per download:** configurable (default: 8) for segment parallelism
- **Queue system:** when a download finishes, the next in queue starts automatically
- **Speed limiting:** optional global speed cap (`max_speed`)
- **ETA calculation:** rolling average (not instantaneous) for stable estimates
- **Failure isolation:** one failed download does not affect others

### Progress UI

```
╭─ Download in corso ──────────────────────────────────────╮
│                                                          │
│  Breaking Bad S01E01     ███████████████░░░░░  74%  12MB/s │
│  Breaking Bad S01E02     ██████████░░░░░░░░░░  48%   9MB/s │
│  Breaking Bad S01E03     ████░░░░░░░░░░░░░░░░  18%  11MB/s │
│                                                          │
│  In coda: 4 episodi rimanenti                            │
│                                                          │
│  ↓ 32MB/s totali  •  ETA ~12 min                         │
╰──────────────────────────────────────────────────────────╯
```

---

## Auto-Update

- On startup, checks GitHub for new versions (non-blocking, 3s timeout)
- If new version found: prompts user to update
- Update process: downloads new package, replaces files, preserves `config.json`, `login.json`, and vault database
- If network unavailable: silently continues without update check
- No `git pull` dependency - works regardless of installation method

---

## Dependencies

### Python Dependencies (requirements.txt)

| Package | Purpose |
|---------|---------|
| httpx>=0.27 | HTTP client (sync mode) |
| curl_cffi>=0.7 | Anti-bot / Cloudflare bypass |
| beautifulsoup4>=4.12 | HTML parsing |
| rich>=13.0 | Terminal UI (tables, progress, colors) |
| pycryptodomex>=3.20 | DRM cryptography |
| pywidevine>=1.8 | Widevine CDM |
| pyplayready>=0.4 | PlayReady CDM |
| unidecode>=1.3 | Filename normalization |
| pathvalidate>=3.2 | Cross-platform path validation |

### System Dependencies

| Dependency | Required | Validated at startup |
|------------|----------|---------------------|
| Python 3.10+ | Yes | Yes, with version check |
| FFmpeg | Yes | Yes, with install instructions per OS |
| FFprobe | Yes | Yes, bundled with FFmpeg |

### External APIs

| Service | Purpose | Fallback |
|---------|---------|----------|
| TMDB | Metadata enrichment (year, genre) | Optional - works without it |
| GitHub | Auto-update check | Silent skip if unavailable |
| cdrm-project.com | Remote Widevine/PlayReady CDM | Local CDM files |

---

## Cross-Platform Support

- **Paths:** `pathlib.Path` everywhere, never raw strings
- **Terminal:** ANSI escape sequences (supported on all modern terminals including Windows Terminal)
- **FFmpeg detection:** OS-specific binary location strategies
- **Encoding:** UTF-8 throughout, `unidecode` for filename sanitization
- **Tested on:** macOS, Linux (Ubuntu/Debian/Fedora), Windows 10/11
- **Windows console:** On `cmd.exe` (Windows 10), virtual terminal processing is enabled via `SetConsoleMode`. Windows Terminal works natively. If alternate screen is unsupported, falls back to `cls`/clear.

---

## Authentication

### Credential Storage

Credentials are stored in `login.json` (plaintext JSON, gitignored). Structure:

```json
{
  "TMDB": {
    "api_key": ""
  },
  "SERVICES": {
    "crunchyroll": {
      "username": "",
      "password": ""
    }
  }
}
```

### Auth Flow per Service

Each service that requires authentication implements an `authenticate()` method in its `ServiceBase` subclass:

```python
class ServiceBase(ABC):
    requires_login: bool = False

    def authenticate(self, credentials: dict) -> AuthSession | None:
        """Returns session cookies/tokens. Called once, cached for session.
           Default: returns None (no auth needed). Override in services
           with requires_login=True."""
        return None

    @abstractmethod
    def search(self, query: str) -> list[MediaEntry]: ...
```

- **On startup:** if a service has `requires_login=True` and credentials are present in `login.json`, it authenticates and caches the session
- **If credentials missing:** the service is still listed but warns "credentials required" when selected
- **If credentials invalid/expired:** clear error message with instructions to update `login.json`
- **Session caching:** auth tokens/cookies are cached in memory for the session lifetime, never written to disk

### AuthSession Model

```python
@dataclass
class AuthSession:
    cookies: dict[str, str]      # Session cookies
    headers: dict[str, str]      # Auth headers (e.g., Bearer token)
    expires_at: float | None     # Unix timestamp, None = session-only
```

### Security

- `login.json` is included in `.gitignore` by default
- A `login.json.example` with empty fields is provided for reference
- No encryption (user is responsible for file system security, same approach as VibraVid)

---

## DRM Workflow

### Key Resolution Chain

```
Content requires DRM decryption
│
├─ 1. Extract PSSH from manifest (MPD/m3u8)
│
├─ 2. Check local vault (SQLite)
│  ├─ Key found → use cached key, skip to step 5
│  └─ Key not found → continue to step 3
│
├─ 3. Request key from remote CDM server
│  ├─ Build challenge from PSSH + CDM device info
│  ├─ Send to service's license URL → get license response
│  ├─ Send license response to CDM server → get decryption keys
│  └─ If server unavailable → try local CDM (step 4)
│
├─ 4. Fallback: local CDM device files
│  ├─ If device files present in data/ → use pywidevine/pyplayready locally
│  └─ If no device files → DRMError with clear message
│
├─ 5. Decrypt content segments with obtained key
│
└─ 6. Cache key in local vault for future use
```

### Vault Schema (SQLite)

```sql
CREATE TABLE drm_keys (
    id INTEGER PRIMARY KEY,
    pssh TEXT NOT NULL,           -- PSSH box (base64)
    kid TEXT NOT NULL,            -- Key ID (hex)
    key TEXT NOT NULL,            -- Content key (hex)
    drm_type TEXT NOT NULL,       -- "widevine" | "playready"
    service TEXT NOT NULL,        -- service short_name
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kid, drm_type)
);
```

### DRM Type Selection

The DRM type (Widevine vs PlayReady) is determined by the service's extractor. Each service knows which DRM system its content uses. The `DRMManager` routes to the appropriate handler based on the DRM type indicated in the manifest.

### CDM Server Configuration (config.json)

```json
"drm": {
    "widevine": {
        "device_type": "ANDROID",
        "system_id": 22590,
        "security_level": 3,
        "host": "https://cdrm-project.com/remotecdm/widevine",
        "secret": "CDRM",
        "device_name": "public"
    },
    "playready": {
        "host": "https://cdrm-project.com/remotecdm/playready",
        "secret": "CDRM",
        "device_name": "public"
    }
}
```

---

## Data Models

### Media Models (`models/media.py`)

```python
@dataclass
class MediaEntry:
    id: str
    title: str
    type: MediaType              # FILM | SERIE | ANIME
    year: int | None
    genre: str | None
    image_url: str | None
    service: str                 # service short_name
    url: str                     # source URL on the service

@dataclass
class Season:
    number: int
    episode_count: int
    title: str | None

@dataclass
class Episode:
    number: int
    season_number: int
    title: str
    url: str
    duration: int | None         # seconds

@dataclass
class SearchResult:
    entry: MediaEntry
    service_display_name: str    # "StreamingCommunity" (display), vs entry.service "sc" (short)
    match_score: float           # 0.0-1.0 fuzzy match
```

### Stream Models (`models/stream.py`)

```python
@dataclass
class VideoTrack:
    id: str
    resolution: str              # "1920x1080"
    codec: str                   # "h264", "h265", "av1"
    bitrate: int | None          # bps
    fps: float | None
    hdr: bool = False

@dataclass
class AudioTrack:
    id: str
    language: str                # ISO 639 code: "ita", "eng"
    codec: str                   # "aac", "opus", "eac3"
    channels: str                # "2.0", "5.1"
    bitrate: int | None

@dataclass
class SubtitleTrack:
    id: str
    language: str                # ISO 639 code
    format: str                  # "srt", "vtt", "ass"
    forced: bool = False

@dataclass
class StreamBundle:
    video: list[VideoTrack]
    audio: list[AudioTrack]
    subtitles: list[SubtitleTrack]
    drm_type: str | None         # "widevine" | "playready" | None
    pssh: str | None             # PSSH box if DRM
    license_url: str | None      # License server URL if DRM

@dataclass
class SelectedTracks:
    video: VideoTrack
    audio: list[AudioTrack]
    subtitles: list[SubtitleTrack]
```

### Event Models (`core/events.py`)

```python
@dataclass
class DownloadProgress:
    download_id: str             # Unique ID for concurrent download disambiguation
    filename: str
    downloaded: int
    total: int
    speed: float                 # bytes/sec

@dataclass
class TrackSelection:
    video_tracks: list[VideoTrack]
    audio_tracks: list[AudioTrack]
    subtitle_tracks: list[SubtitleTrack]

@dataclass
class DownloadComplete:
    download_id: str
    filepath: Path
    duration: float
    size: int

@dataclass
class ErrorEvent:
    download_id: str | None
    error: StreamloadError
    message: str
    recoverable: bool

@dataclass
class WarningEvent:
    message: str
    context: str | None
```

---

## Service Auto-Discovery Mechanism

On startup, `ServiceRegistry` imports all service modules via an explicit import list in `services/__init__.py`:

```python
# services/__init__.py
from streamload.services import (
    animeunity, animeworld, crunchyroll, discovery, dmax,
    foodnetwork, guardaserie, homegardentv, mediasetinfinity,
    mostraguarda, nove, raiplay, realtime, streamingcommunity, tubitv,
)
```

Each service module's `__init__.py` contains the `@ServiceRegistry.register` decorated class. The import triggers registration. Adding a new service requires: (1) create the module, (2) add one import line. This is explicit and predictable, unlike VibraVid's filesystem-scanning approach.

---

## Concurrency Model

The download pipeline uses **threading** (not asyncio) for simplicity and compatibility:

- `httpx` is used in **sync mode** (not async)
- `DownloadManager` uses `concurrent.futures.ThreadPoolExecutor` for parallel downloads
- Each download uses a separate `ThreadPoolExecutor` for segment parallelism
- `max_concurrent` controls the outer pool (default: 3 downloads)
- `thread_count` controls the inner pool (default: 8 threads per download)

This avoids the complexity of async while providing sufficient concurrency for I/O-bound download work. The bottleneck is network bandwidth, not thread overhead.

---

## Retry Configuration Clarification

Two separate retry settings exist for different layers:

| Setting | Scope | Default | Purpose |
|---------|-------|---------|---------|
| `download.retry_count` | Segment level | 25 | Retries for individual video/audio segment downloads (HLS/DASH) |
| `network.max_retry` | HTTP level | 8 | Retries for general HTTP requests (search, API calls, manifest fetches) |

Segment downloads have higher retry tolerance because a single failed segment in a 500-segment stream should not abort the entire download.

---

## Output Template Variables

### Movie format (default: `{title} ({year})`)

| Variable | Example |
|----------|---------|
| `{title}` | "The Matrix" |
| `{year}` | "1999" |

### Episode format (default: `{series}/S{season:02d}/{title} S{season:02d}E{episode:02d}`)

| Variable | Example |
|----------|---------|
| `{series}` | "Breaking Bad" |
| `{season}` | 1 (supports format spec: `{season:02d}` → "01") |
| `{episode}` | 3 (supports format spec: `{episode:02d}` → "03") |
| `{title}` | "...And the Bag's in the River" |

### Speed limit format

`max_speed` accepts: `"10MB"` (megabytes/sec), `"500KB"` (kilobytes/sec), or `null`/empty for unlimited.

---

## Film-Only Services

Services categorized as `FILM` (e.g., MostraGuarda) implement `get_seasons()` and `get_episodes()` to return empty lists. The `get_streams()` method accepts both `Episode` and `MediaEntry` via a union type:

```python
def get_streams(self, item: Episode | MediaEntry) -> StreamBundle: ...
```

For films, the CLI skips the season/episode selection and passes the `MediaEntry` directly to `get_streams()`.
