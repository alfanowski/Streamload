# v3 UI/UX Refactor — Design

**Date:** 2026-05-16
**Scope:** Sub-plan 8 (Netflix×AppleTV-style UI refactor)
**Status:** Approved — ready for implementation plan

## Goal

Replace the current functional-but-utilitarian UI with a cinematic, "premium streaming app" experience in the style of Netflix + Apple TV. Plugins become invisible to the user (no settings management, no source badges), and titles that can't be played show a soft "Al momento non disponibile" state instead of clickable buttons that throw errors.

## Aesthetic direction

**Mix Netflix × Apple TV.** Concretely:

- **Backgrounds:** never pure black. Dark gradient base `#0e0e16 → #1a1428` with soft radial accents in the hero based on the title's dominant color.
- **Surfaces:** glassmorphism (`rgba(255,255,255,.06–.15)` + 20px blur) for buttons, dropdowns, popovers. Card surfaces with deep shadows `0 10px 30px rgba(0,0,0,.5)`.
- **CTAs:** white pill buttons (`rgba(255,255,255,.95)` on black text) for the primary action; glass pill (`rgba(255,255,255,.1)` blur on white text) for secondary.
- **Accent:** white-on-white-rounded, no red CTA spotlight. Status indicators (live, badges) use a muted green `#9aff9a` or pale gold `#ffd980` — not Netflix red.
- **Typography:** Inter or SF Pro for body, with a heavier display weight for hero titles (~800, letter-spacing -1px). Monospaced face for metadata labels ("IN EVIDENZA", "EPISODI", durations) — establishes the "indie editorial" feel that distinguishes us from a Netflix clone.
- **Corners:** generous (12-24px on cards, 18-20px on pill buttons, 4-6px on small chips).
- **Motion:** restrained. 200-300ms ease-out for hovers, 7s auto-rotate on hero, 600ms cross-fade between hero slides.

## Decisions taken

1. **Hero:** trailer-driven, 5 featured titles, rotates every ~30s. Starts as backdrop image; after 2s the YouTube trailer plays muted (mute=1, autoplay=1, controls=0). 🔊 toggle in the bottom-right of the hero. Pause auto-rotation on hover. Title-page hero follows the same pattern (2s static → trailer).
2. **Plugins are invisible.** No badges on poster cards, no "Sorgente: X" in title page metadata, no per-row plugin filters. The router does its thing silently. The user never knows which plugin served what.
3. **Settings has no plugin section.** No installed-plugins list, no enable/disable toggle, no "Aggiorna pacchetto plugin" button, no per-row remove. Updates happen automatically in the background (existing 30-min poller + the future event-driven mechanism in sub-plan 6c). The GitHub PAT bootstrap stays only at first-run onboarding — it's a one-time setup, not a "settings" concern.
4. **Unavailable state:** the "Guarda" button becomes semi-transparent (opacity ~0.45, glass surface dimmed) with label "Al momento non disponibile", non-clickable. Triggered when a pre-check against all matching plugins returns no playable bundle. Pre-check fires on title page open and is cached per `(tmdbId, mediaType)` for 30 min.
5. **Navigation:** Netflix-style top bar — logo (left) · Home · Film · Serie TV · Anime · La mia lista · 🔍 · avatar. Bar is `rgba(10,8,18,.85)` with 20px blur over the content; becomes solid `#0a0814` once the user scrolls past 80px. Settings + logout live in the avatar popover.
6. **Home rows:** rich Netflix layout, 8-10 rows. See § Page specs · Home for the exact list and data sources.
7. **Title page:** Netflix-completo. Backdrop with trailer (mirrors hero behavior) + primary CTAs + synopsis. Right sidebar holds cast / created-by / genres. Below: episodes (with thumbs) for TV, then "Titoli simili" row.
8. **Search:** click 🔍 → fullscreen overlay (blur + glass) with the input field large + live suggestions (top 5) as the user types. Enter or "Mostra tutti i risultati" navigates to `/search?q=…` which is a dedicated grid page with filter chips (Tutto / Film / Serie TV / Anime).

## Page specs

### Home (`/home`)

**Layout, top to bottom:**

1. **Top bar** (fixed, transparent over hero, solid over rows). Avatar popover: profile name + email · Impostazioni · Esci.
2. **Hero** (full-width, ~480px tall on desktop). Backdrop image from TMDB → after 2s, YouTube trailer iframe (muted, autoplay, no controls). Bottom-left overlay: monospace label "IN EVIDENZA · 2 DI 5", title (display-weight, 36-44px), short meta line (`2025 · 8 episodi · IT · ⭐ 7.8`), two-line synopsis (max ~120 chars), CTAs `▶ Guarda` (white pill) + `＋ La mia lista` (glass pill) + 🔊 (glass circular). Indicator bar bottom-right (5 dashes, active = larger and brighter). Arrows ◀ ▶ appear on hover left/right.
3. **Rows:**
   - **Continua a guardare** — landscape backdrop cards (16:9) with progress bar overlay. Source: `watch_progress` ordered by `last_seen_at desc`. Hidden if empty.
   - **Tendenze oggi** — poster cards (2:3). Source: TMDB `/trending/all/day`.
   - **Nuove uscite** — poster cards. Source: TMDB `/discover/movie?sort_by=release_date.desc&primary_release_date.gte=<60d ago>` ∪ `/discover/tv?sort_by=first_air_date.desc&...`.
   - **Per genere · Crime & Thriller** — TMDB `/discover/movie?with_genres=80,53` ∪ tv equivalent.
   - **Per genere · Commedie italiane** — `/discover/movie?with_genres=35&with_original_language=it`.
   - **Anime** — `/discover/tv?with_keywords=210024` (Anime keyword) or capability-aware filter.
   - **Documentari** — `/discover/tv?with_genres=99` ∪ movie.
   - **La mia lista** — favorites ∪ watchlist (dedup by tmdbId). Hidden if empty.
   - **Visti di recente** — `watch_progress` finished items ordered by `last_seen_at desc`. Hidden if empty.
   - **Top di sempre** — TMDB `/movie/top_rated` ∪ `/tv/top_rated`.
4. **Card hover behavior** (Netflix-style): 200ms scale to 1.08, soft shadow appears, after 600ms hover the card pops up showing title + year + chevron-down for the title page. No video preview on hover (heavy + complex — defer).

**Loading state:** skeleton row with shimmer placeholders (3 wide rows + 7 poster rows).

**Empty state:** "Cerca un titolo o guarda le tendenze" if user has no progress / no list, with a `🔍 Cerca` CTA.

### Title page (`/title/:tmdbId`)

**Layout, top to bottom:**

1. **Top bar** — transparent, fades to solid as user scrolls.
2. **Hero** (~440px tall) — same trailer-after-2s pattern as Home. Backdrop with darker bottom gradient. Bottom-left: title (display, 36px), monospace meta (`2025 · 8 ep · IT · ⭐ 7.8 · TV-MA`), 2-line synopsis. CTAs:
   - `▶ Guarda S1 E1` (or `Riprendi` if `watch_progress` exists; or `Al momento non disponibile` semi-transparent if pre-check returned 0 results)
   - `＋ La mia lista` (or `✓ Nella lista`)
   - `↗` Share (copies a deep link)
3. **Below the hero, 2-column layout:**
   - **Left (2/3 width)** — Trama completa (multiline, no truncation). Then for TV: `Episodi · S{n}` heading + season picker (chips) + episode list (thumb + number + title + duration + still-from-tmdb). For movies: skip episodes section.
   - **Right (1/3 width)** — `CAST` (top 5 names) · `CREATO DA` · `GENERI`. Each as a label + comma-separated values. TMDB credits + details endpoint.
4. **Bottom row:** `Titoli simili` — poster row of TMDB recommendations (`/movie/{id}/recommendations` or `/tv/{id}/recommendations`).

**Pre-check timing:** on `initState`, kick off `router.probeAvailability(tmdbId, mediaType, season=1, episode=1)`. Show the `Guarda` CTA in a "checking" state (small spinner inside the pill) for the first ~800ms. If the probe returns true → enable CTA. If false → swap CTA to the unavailable state (label + opacity reduction + non-clickable).

### Watch page (`/watch/:tmdbId`)

Mostly already implemented. Visual changes:

- Keep custom `PlayerControls` but update font + spacing to match the new tokens.
- Audio/subtitle popups already done — restyle to match (glass surface, monospace labels).
- Close button (top-left) → restyle as glass circular `←`.
- On exit, navigate back via `context.go('/title/$tmdbId?...')` so the user lands on the title page they came from (not always `/home`).

### Search

- **Trigger:** 🔍 icon in top bar OR `Cmd+K` shortcut.
- **Overlay:** fixed, `rgba(0,0,0,.85) + 40px blur` over the current page. Centered input (22px font, no border, white caret). `Esc` text indicator top-right. Suggestions appear under the input as the user types (debounce 200ms), showing the first 5 matches from TMDB `/search/multi?query=…`, each with a small poster thumb, title, and `Type · Year` line. Selecting a suggestion → `/title/:tmdbId` directly.
- **Full results:** Enter OR "Mostra tutti i risultati →" (last item) → `context.go('/search?q=<query>')`. The `/search` page has the top bar restored, a filter chip row (Tutto / Film / Serie TV / Anime) under it, and a 5-column grid of poster cards below. Pagination via TMDB `page=N`.

### Settings (`/settings`)

Currently has plugin manager. **Strip all plugin UI.** Remaining sections:

- **Account** — read-only: GitHub avatar + name + email. Logout button (red destructive).
- **Aspetto** — theme: only "Scuro" (no light mode for v1). Language: only IT for v1. Both shown as locked / read-only with "in arrivo".
- **Riproduzione** — preferred audio language (default IT), preferred subtitle language (default OFF). These feed into the existing engine auto-pick.
- **Sviluppatore** (only visible if a `--debug` flag at build time) — last plugin refresh time, force-refresh button, GitHub PAT status. Hidden in release.
- **About** — version (`pubspec.yaml`), GitHub link, license.

### Plugin onboarding (`/onboarding/plugins`)

Stays mostly as-is but restyled to the new tokens. Single screen: paste PAT → verify → done. After successful first-run setup, this route is never reachable from the UI (deep link only). No "Cambia token GitHub" entry in Settings.

## Architecture changes

### New design token system

```
lib/presentation/theme/
├── colors.dart           extend with: bgBase, bgGradientStart, surfaceGlass*,
│                         heroOverlay, textPrimary/Secondary/Muted, success, warn
├── typography.dart       extend with: display1 (36/800/-1px), display2 (24/700),
│                         mono (10-11/JetBrains Mono), labelMono (9/2px-tracking)
├── spacing.dart          NEW: tokens for row/page padding, gap between rows, card gaps
└── motion.dart           NEW: durations + easings (hover, hero rotate, page transition)
```

Existing `StreamloadColors` / `StreamloadTypography` get new fields; old fields kept for backward-compat until all call sites migrate.

### New shared widgets

```
lib/presentation/widgets/
├── hero/
│   ├── hero_carousel.dart     5-title carousel + auto-rotate + indicator
│   ├── hero_trailer.dart      YouTube iframe wrapper (uses webview_flutter)
│   └── hero_slide.dart        single slide layout
├── rows/
│   ├── poster_row.dart        horizontal scroll of 2:3 PosterCard
│   ├── backdrop_row.dart      horizontal scroll of 16:9 BackdropCard (continue-watching)
│   └── row_header.dart        title + count chip + "Vedi tutti" link
├── cards/
│   ├── poster_card.dart       UPDATE existing — hover scale + bottom title fade-in
│   └── backdrop_card.dart     NEW — landscape 16:9 with progress bar
├── play_cta.dart              NEW — pill button with "checking / play / unavailable" states
├── top_nav_bar.dart           NEW — sticky top nav with scroll-aware background
├── avatar_menu.dart           NEW — popover with name/email/Impostazioni/Esci
└── search_overlay.dart        NEW — fullscreen blur + input + live suggestions
```

### Page rewrites

```
lib/presentation/pages/
├── home_page.dart           REWRITE — hero + 8-10 rows + tab filters
├── title_page.dart          REWRITE — backdrop hero + 2-column + similar row
├── watch_page.dart          minor restyle (existing logic kept)
├── search_page.dart         NEW (replaces inline search in home)
├── settings_page.dart       strip plugin sections
└── plugin_onboarding_page.dart    restyle only
```

### Router changes

```dart
GoRoute('/search', builder: (ctx, state) => SearchPage(query: state.uri.queryParameters['q'] ?? '')),
GoRoute('/film', builder: ... => HomePage(filter: 'movie')),
GoRoute('/serie', builder: ... => HomePage(filter: 'tv')),
GoRoute('/anime', builder: ... => HomePage(filter: 'anime')),
GoRoute('/list', builder: ... => MyListPage()),
```

`HomePage(filter:)` is the same page; the filter chip drives a different row composition (only relevant TMDB endpoints).

### Trailer infra

Add `webview_flutter: ^4.x` and `webview_flutter_wkwebview: ^3.x` for macOS. `HeroTrailer` widget receives a YouTube video ID and renders:

```dart
WebViewWidget(controller: WebViewController()
  ..loadHtmlString(_iframeHtml(videoId))
  ..setJavaScriptMode(JavaScriptMode.unrestricted)
  ..setBackgroundColor(Colors.transparent))
```

Where `_iframeHtml(id)` is a tiny page that embeds the IFrame Player API with `autoplay=1&mute=1&controls=0&modestbranding=1&playsinline=1&rel=0`. The widget also exposes a `setMuted(bool)` JavaScript callback wired to the 🔊 toggle.

**Trailer source:** TMDB `/movie/{id}/videos` or `/tv/{id}/videos` → pick the first result where `site == "YouTube"` AND `type in ("Trailer","Teaser")` AND `official == true`, fallback to any YouTube Trailer/Teaser, fallback to `null` (no trailer → just static backdrop).

### Pre-check availability infra

Extend `ProviderRouter` with:

```dart
Future<bool> probeAvailability({
  required String mediaType,
  required TitleHint hint,
  int? season,
  int? episode,
}) async { ... }
```

Runs `_resolveEntry` on each matching plugin in parallel with a 4s deadline. Returns true if any plugin found a non-null match. Results cached in an in-memory LRU keyed by `(tmdbId, mediaType, season?, episode?)`, 30-min TTL. The cache survives across `PlayController` rebuilds because `ProviderRouter` is held in `playControllerProvider` (already non-autoDispose).

### Catalog row endpoints

Add a `catalog_rows_api.dart` wrapping the backend's existing TMDB-mirror endpoints. The backend may need a thin proxy endpoint per row category if TMDB rate-limiting becomes an issue; for v1 we hit TMDB directly via the existing `catalog_api`.

```dart
abstract class CatalogRowsApi {
  Future<List<MediaSummary>> trendingDay();
  Future<List<MediaSummary>> trendingWeek();
  Future<List<MediaSummary>> newReleases({String mediaType});
  Future<List<MediaSummary>> byGenre({List<int> genreIds, String mediaType});
  Future<List<MediaSummary>> topRated({String mediaType});
}
```

Riverpod providers wrap each. Home page uses `FutureProvider.family<List<MediaSummary>, RowKey>`.

## Color palette (concrete values)

```dart
// Backgrounds — never pure black
bgBase           = #0e0e16
bgGradientStart  = #1a1428
bgGradientEnd    = #0e0e16
bgScrolled       = #0a0814   // top bar background once user scrolls

// Surfaces (glass)
surfaceGlass     = rgba(255,255,255,.06)
surfaceGlassHi   = rgba(255,255,255,.10)
surfaceGlassMax  = rgba(255,255,255,.15)
borderGlass      = rgba(255,255,255,.08)

// Text
textPrimary      = #ffffff
textSecondary    = rgba(255,255,255,.65)
textMuted        = rgba(255,255,255,.45)

// CTAs
ctaPrimaryBg     = rgba(255,255,255,.95)
ctaPrimaryFg     = #000000
ctaSecondaryBg   = rgba(255,255,255,.10)
ctaUnavailableBg = rgba(255,255,255,.04)
ctaUnavailableFg = rgba(255,255,255,.45)

// Status
success          = #9aff9a   // "disponibile su X" chip (debug-only)
warn             = #ffd980
```

## Typography (concrete)

```dart
displayHero    = Inter 36/800/-1px       // hero title
displayPage    = Inter 28/700/-0.6px     // title page title
sectionHeader  = Inter 14/600/0.5px      // row header "Tendenze oggi"
body           = Inter 14/400/0          // synopsis, descriptions
bodySmall      = Inter 12/400/0
metaMono       = JetBrains Mono 11/400/0 // "2025 · 8 ep · IT · ⭐ 7.8"
labelMono      = JetBrains Mono 9/600/2px-tracking-uppercase  // "IN EVIDENZA"
ctaLabel       = Inter 12/600/0          // pill button text
```

Two-font system. Inter for everything readable, mono for "metadata as data" — that distinguishes us from pure Netflix.

## Test plan

- **Unit:** `_scoreFor` in router stays green (existing tests).
- **Unit:** `probeAvailability` returns true when any plugin matches; false when none; respects deadline; caches results.
- **Widget:** `HeroCarousel` rotates after 7s, pauses on hover, indicator updates.
- **Widget:** `PlayCta` renders in 3 states (checking / play / unavailable) based on a provided availability stream.
- **Widget:** `SearchOverlay` shows suggestions after 200ms debounce, navigates on Enter.
- **Widget:** `BackdropCard` shows progress bar when `progressFraction` is set.
- **Golden:** `HeroSlide` renders consistently with mocked TMDB data (one snapshot).
- **Integration (manual):** end-to-end with real data — open the app, scroll Home, tap a title, see trailer load, tap Guarda, watch plays. Try a title with no plugin match → see "Al momento non disponibile".

## Non-goals (this round)

- Personalized recommendations ("Perché hai guardato X") — needs a rec engine, not worth it for ~10 users
- Multi-profile (Netflix-style profile picker) — single profile per account is fine
- Live-channel browsing — out of scope (we're VOD)
- Downloads — out of scope (streaming only)
- Light theme — dark only for v1
- IT only — language picker shown but locked
- Video preview on card hover — heavy, can add later
- Per-row "Vedi tutti" full pages — chip filters in Home cover most needs
- Search filters by genre/year/rating — chip filters by type only for v1
- Reordering rows, "more like this" rabbit holes — defer

## Mobile / responsive design

Flutter ships iOS + Android out of the box; the same widgets render on phone, but the layouts and interactions need to adapt. Three breakpoints drive everything:

```dart
class Breakpoints {
  static const phone   = 600;   // < 600 px → phone (portrait + landscape)
  static const tablet  = 900;   // 600..899 → tablet
  // >= 900 → desktop
}
```

`Responsive` helper widget exposes `isPhone(context)`, `isTablet(context)`, `isDesktop(context)` via `MediaQuery.sizeOf(context).width`.

### Per-surface adaptations

**Navigation**
- **Desktop / tablet:** top bar as specified (logo + 5 tabs + search + avatar). Bar collapses at 900-1100 by dropping spacing.
- **Phone:** top bar shrinks to logo + 🔍 + avatar only. Categories move to a **bottom tab bar**: Home · Cerca · La mia lista · Profilo. Film / Serie TV / Anime become **filter chips** under the hero on Home (style C from the earlier nav screen, applied only to phone). Settings + logout live behind the Profilo tab on phone (no avatar popover — full-page profile screen).

**Hero**
- **Desktop:** ~480px tall, metadata at bottom-left in a single horizontal block.
- **Tablet:** ~360px tall, same layout but compressed.
- **Phone:** **65% of viewport height**, full-width. Metadata stacked vertically (title → meta line → 2-line synopsis → CTAs). CTAs become full-width on phones < 380px wide. Trailer behavior identical (WebView works on iOS / Android via webview_flutter).
- Indicator dots: smaller on phone. Hover-to-pause replaced by **tap-anywhere-to-pause** + tap again to resume.

**Rows**
- **Desktop:** poster cards 160w / backdrop cards 320w. ~6 visible per viewport.
- **Tablet:** poster 130 / backdrop 260. ~5 visible.
- **Phone:** poster 110 / backdrop 220. ~2-3 visible. Snap-scrolling enabled (`PageScrollPhysics` with `ClampingScrollPhysics` fallback) so cards center neatly after a fling.
- "Vedi tutti" link in the row header navigates to a `/list/<rowKey>` grid page — same as desktop but more useful on phone since rows are narrower.

**Card interaction**
- **Desktop:** hover scale + popup with chevron-down.
- **Mobile (phone + tablet):** no hover effects. Tap → navigate to title page. Long-press → context menu (`Aggiungi a Lista` / `Condividi`).

**Title page**
- **Desktop:** 2-column body (synopsis 2/3 | cast sidebar 1/3).
- **Tablet:** still 2-column but narrower sidebar.
- **Phone:** **single column stacked**. Order: hero → CTAs → synopsis → "Mostra dettagli" expandable that reveals Cast / Created by / Genres → Episodi (full-width list, each row has thumb 80×45 + title + duration + chevron) → "Titoli simili" horizontal row. Episodes list uses `ListView.separated` (not a horizontal scroll like rows).

**Watch page**
- **Desktop:** floating glass controls at bottom.
- **Phone (portrait):** video on top in 16:9, with the **title + episode info + Continua a guardare** stack below. Tap on the video toggles fullscreen.
- **Phone (landscape) / fullscreen:** edge-to-edge video, controls overlay on tap. Bigger touch targets (44pt min per Apple HIG). Audio / subtitle popups become **bottom sheets** instead of dropdown menus. Add a `←` close button top-left (currently desktop has it; mobile gets it too).
- **Gestures (phone only):** double-tap left → -10s, double-tap right → +10s. Vertical drag on right half → volume; on left half → brightness (only if running in fullscreen / immersive). Horizontal drag → scrub.

**Search**
- **Desktop:** 🔍 in top bar opens overlay.
- **Phone:** 🔍 tab in bottom bar navigates to `/search`. The "overlay" is the page itself — input at top, suggestions inline as you type, full grid below when query is committed. Skip the modal/blur step (modals on phone feel cramped).

### Per-input adaptations

- Touch targets ≥ 44pt on phone (Apple HIG).
- All hover states have a tap-equivalent.
- `Cmd+K` shortcut for search → desktop only; no equivalent on phone (always one tap away in bottom nav).
- Pull-to-refresh on Home + Search results pages on phone (`RefreshIndicator`).
- Swipe-back gesture on title / watch pages (iOS-style edge-swipe to pop).

### Implementation footprint

Mobile is **not** a separate codebase — same widgets, conditional layouts:

```dart
LayoutBuilder(builder: (ctx, c) {
  final width = c.maxWidth;
  if (width < Breakpoints.phone) return _HomeMobile();
  if (width < Breakpoints.tablet) return _HomeTablet();
  return _HomeDesktop();
});
```

Most widgets get a single layout that parametrizes on `Responsive.isPhone(ctx)`. Only Home, Title, Watch have meaningfully different mobile structures (separate sub-widgets).

### iOS / Android specifics

- **iOS:** keep the SF-feel typography. Add `cupertino_icons` package (already a Flutter standard). Status bar adapts to dark theme. App icon + launch screen need updating (kept as v2 stubs for now).
- **Android:** edge-to-edge with system UI behind transparent app bars. Material 3 ripples on cards (already default in Flutter).
- **Both:** background audio when player is in foreground — not in scope for v1 (defer to a future audio session sub-plan).

### Testing on mobile

- Use Flutter Inspector + the responsive preview (Cmd+Alt+R in VS Code) to test all breakpoints from the desktop dev machine.
- For real-device testing: deploy to a physical iPhone via Xcode (operator has macOS + Xcode), and an Android emulator if needed. Mobile final QA is a manual sweep at the end of each phase, not a per-task gate.

## Implementation phasing (informs writing-plans)

- **Phase A — Tokens & primitives**
  Design tokens (colors, typography, spacing, motion) + base widgets (PosterCard hover, BackdropCard, RowHeader, PlayCta).
- **Phase B — Navigation shell**
  TopNavBar, AvatarMenu, route additions (`/film`, `/serie`, `/anime`, `/list`, `/search`).
- **Phase C — Hero infra**
  webview_flutter dependency + HeroTrailer + HeroSlide + HeroCarousel. TMDB videos API wiring.
- **Phase D — Home page**
  Row composition + catalog_rows providers + the 8-10 rows + filter chips for `/film`, `/serie`, `/anime`.
- **Phase E — Title page rewrite**
  Backdrop hero (reusing HeroTrailer) + 2-column body + episode list with thumbs + similar row.
- **Phase F — Pre-check availability**
  Router.probeAvailability + cache + wire to PlayCta.
- **Phase G — Search**
  SearchOverlay + /search page + filter chips + grid.
- **Phase H — Settings strip**
  Remove plugin manager UI. Add Account/Aspetto/Riproduzione/About sections.
- **Phase I — Onboarding restyle**
  Restyle plugin_onboarding_page to new tokens, no logic changes.

Each phase is independently shippable and testable. Phases A-B are foundation. Phases C-E are the user-visible "wow". Phase F is the "Al momento non disponibile" polish. Phases G-I are cleanup.

**Mobile is cross-cutting.** Every phase ships with phone + tablet + desktop layouts in one go (the `Responsive` helper + `LayoutBuilder` pattern in § Mobile / responsive design). No separate mobile phase — that would double the work and let the two surfaces drift. Real-device manual QA at the end of each phase.
