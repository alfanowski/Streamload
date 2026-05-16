# v3 UI/UX Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Netflix×Apple TV refactor across desktop/tablet/phone per docs/superpowers/specs/2026-05-16-v3-ui-refactor-design.md.

**Architecture:** Flutter responsive single-codebase. Existing player/router/proxy/plugin runtime stay untouched. Visual + nav + page-structure rewrite only. Mobile is cross-cutting, not a separate codebase or phase.

**Tech Stack:** Flutter 3.41, Dart 3.11, riverpod 2.6, go_router, drift, webview_flutter (new), existing media_kit player.

---

## Phase A — Design tokens & responsive primitives

Foundational work. After this phase, every subsequent task uses the same tokens.

### Task A1: Extend design tokens

**Files:**
- Modify: `lib/presentation/theme/colors.dart`
- Modify: `lib/presentation/theme/typography.dart`
- Create: `lib/presentation/theme/spacing.dart`
- Create: `lib/presentation/theme/motion.dart`

- [ ] **Step 1: Extend `colors.dart`** with the palette from spec § Color palette.

```dart
class StreamloadColors {
  // existing fields stay
  static const bgBase = Color(0xFF0E0E16);
  static const bgGradientStart = Color(0xFF1A1428);
  static const bgGradientEnd = Color(0xFF0E0E16);
  static const bgScrolled = Color(0xFF0A0814);

  static Color surfaceGlass = Colors.white.withValues(alpha: 0.06);
  static Color surfaceGlassHi = Colors.white.withValues(alpha: 0.10);
  static Color surfaceGlassMax = Colors.white.withValues(alpha: 0.15);
  static Color borderGlass = Colors.white.withValues(alpha: 0.08);

  static const textPrimary = Color(0xFFFFFFFF);
  static Color textSecondary = Colors.white.withValues(alpha: 0.65);
  static Color textMuted = Colors.white.withValues(alpha: 0.45);

  static Color ctaPrimaryBg = Colors.white.withValues(alpha: 0.95);
  static const ctaPrimaryFg = Color(0xFF000000);
  static Color ctaSecondaryBg = Colors.white.withValues(alpha: 0.10);
  static Color ctaUnavailableBg = Colors.white.withValues(alpha: 0.04);
  static Color ctaUnavailableFg = Colors.white.withValues(alpha: 0.45);

  static const success = Color(0xFF9AFF9A);
  static const warn = Color(0xFFFFD980);
}
```

- [ ] **Step 2: Extend `typography.dart`** with the new scales from spec § Typography.

```dart
class StreamloadTypography {
  static TextStyle displayHero({Color? color}) => TextStyle(
        fontFamily: 'Inter',
        fontSize: 36,
        fontWeight: FontWeight.w800,
        letterSpacing: -1.0,
        color: color ?? StreamloadColors.textPrimary,
      );

  static TextStyle displayPage({Color? color}) => TextStyle(
        fontFamily: 'Inter',
        fontSize: 28,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.6,
        color: color ?? StreamloadColors.textPrimary,
      );

  static TextStyle sectionHeader({Color? color}) => TextStyle(
        fontFamily: 'Inter',
        fontSize: 14,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.5,
        color: color ?? StreamloadColors.textPrimary,
      );

  static TextStyle metaMono({Color? color}) => TextStyle(
        fontFamily: 'JetBrainsMono',
        fontSize: 11,
        fontWeight: FontWeight.w400,
        color: color ?? StreamloadColors.textSecondary,
      );

  static TextStyle labelMono({Color? color}) => TextStyle(
        fontFamily: 'JetBrainsMono',
        fontSize: 9,
        fontWeight: FontWeight.w600,
        letterSpacing: 2.0,
        color: color ?? StreamloadColors.textMuted,
      );

  static TextStyle ctaLabel({Color? color}) => TextStyle(
        fontFamily: 'Inter',
        fontSize: 12,
        fontWeight: FontWeight.w600,
        color: color ?? StreamloadColors.ctaPrimaryFg,
      );

  // existing body / mono / etc. methods stay
}
```

- [ ] **Step 3: Add `Inter` and `JetBrainsMono` fonts.** Download from Google Fonts. Files to add: `assets/fonts/Inter-Regular.ttf`, `Inter-SemiBold.ttf`, `Inter-Bold.ttf`, `Inter-ExtraBold.ttf`, `JetBrainsMono-Regular.ttf`, `JetBrainsMono-SemiBold.ttf`. Register in `pubspec.yaml`:

```yaml
flutter:
  fonts:
    - family: Inter
      fonts:
        - asset: assets/fonts/Inter-Regular.ttf
        - asset: assets/fonts/Inter-SemiBold.ttf
          weight: 600
        - asset: assets/fonts/Inter-Bold.ttf
          weight: 700
        - asset: assets/fonts/Inter-ExtraBold.ttf
          weight: 800
    - family: JetBrainsMono
      fonts:
        - asset: assets/fonts/JetBrainsMono-Regular.ttf
        - asset: assets/fonts/JetBrainsMono-SemiBold.ttf
          weight: 600
```

- [ ] **Step 4: Create `spacing.dart`**:

```dart
class StreamloadSpacing {
  static const rowGap = 28.0;
  static const pagePaddingDesktop = EdgeInsets.symmetric(horizontal: 48);
  static const pagePaddingTablet = EdgeInsets.symmetric(horizontal: 32);
  static const pagePaddingPhone = EdgeInsets.symmetric(horizontal: 16);
  static const cardGap = 8.0;
  static const cardRadius = 6.0;
  static const cardRadiusLarge = 12.0;
  static const pillRadius = 20.0;
}
```

- [ ] **Step 5: Create `motion.dart`**:

```dart
class StreamloadMotion {
  static const hoverDuration = Duration(milliseconds: 200);
  static const hoverCurve = Curves.easeOut;
  static const heroRotateInterval = Duration(seconds: 30);
  static const heroCrossfade = Duration(milliseconds: 600);
  static const carouselSlideEvery = Duration(seconds: 7);
  static const pageTransition = Duration(milliseconds: 250);
}
```

- [ ] **Step 6: Run flutter pub get + analyze**

Run: `flutter pub get && flutter analyze --no-pub`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add lib/presentation/theme/ pubspec.yaml assets/fonts/
git commit -m "ui(tokens): add Inter+JetBrainsMono fonts + color/typo/spacing/motion tokens (Phase A1)"
```

### Task A2: Responsive helper + Breakpoints

**Files:**
- Create: `lib/presentation/responsive.dart`
- Test: `test/presentation/responsive_test.dart`

- [ ] **Step 1: Write the failing test**

```dart
// test/presentation/responsive_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/presentation/responsive.dart';

void main() {
  testWidgets('Responsive classifies width into phone/tablet/desktop',
      (tester) async {
    late bool isPhone, isTablet, isDesktop;
    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(size: Size(400, 800)),
      child: Builder(builder: (ctx) {
        isPhone = Responsive.isPhone(ctx);
        isTablet = Responsive.isTablet(ctx);
        isDesktop = Responsive.isDesktop(ctx);
        return const SizedBox();
      }),
    ));
    expect(isPhone, isTrue);
    expect(isTablet, isFalse);
    expect(isDesktop, isFalse);

    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(size: Size(750, 1024)),
      child: Builder(builder: (ctx) {
        isPhone = Responsive.isPhone(ctx);
        isTablet = Responsive.isTablet(ctx);
        return const SizedBox();
      }),
    ));
    expect(isPhone, isFalse);
    expect(isTablet, isTrue);

    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(size: Size(1400, 900)),
      child: Builder(builder: (ctx) {
        isDesktop = Responsive.isDesktop(ctx);
        return const SizedBox();
      }),
    ));
    expect(isDesktop, isTrue);
  });
}
```

- [ ] **Step 2: Run test, verify FAIL** — `responsive.dart` doesn't exist.

- [ ] **Step 3: Implement**

```dart
// lib/presentation/responsive.dart
import 'package:flutter/widgets.dart';

class Breakpoints {
  static const phone = 600.0;
  static const tablet = 900.0;
}

class Responsive {
  static double widthOf(BuildContext context) =>
      MediaQuery.sizeOf(context).width;

  static bool isPhone(BuildContext context) =>
      widthOf(context) < Breakpoints.phone;
  static bool isTablet(BuildContext context) {
    final w = widthOf(context);
    return w >= Breakpoints.phone && w < Breakpoints.tablet;
  }
  static bool isDesktop(BuildContext context) =>
      widthOf(context) >= Breakpoints.tablet;
  static bool isMobile(BuildContext context) =>
      widthOf(context) < Breakpoints.tablet;
}
```

- [ ] **Step 4: Run test** — PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/presentation/responsive.dart test/presentation/
git commit -m "ui(responsive): Breakpoints + Responsive helper (Phase A2)"
```

### Task A3: PlayCta widget (3 states)

**Files:**
- Create: `lib/presentation/widgets/play_cta.dart`
- Test: `test/widgets/play_cta_test.dart`

- [ ] **Step 1: Write failing test**

```dart
// test/widgets/play_cta_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/presentation/widgets/play_cta.dart';

void main() {
  Widget host(Widget child) => MaterialApp(home: Scaffold(body: child));

  testWidgets('checking state shows spinner', (t) async {
    await t.pumpWidget(host(PlayCta(state: PlayCtaState.checking, onTap: () {})));
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });
  testWidgets('play state shows label + is tappable', (t) async {
    var tapped = false;
    await t.pumpWidget(host(PlayCta(
        state: PlayCtaState.play, label: 'Guarda', onTap: () => tapped = true)));
    expect(find.text('▶ Guarda'), findsOneWidget);
    await t.tap(find.byType(PlayCta));
    expect(tapped, isTrue);
  });
  testWidgets('unavailable state is non-tappable + dimmed', (t) async {
    var tapped = false;
    await t.pumpWidget(host(PlayCta(
        state: PlayCtaState.unavailable, onTap: () => tapped = true)));
    expect(find.text('Al momento non disponibile'), findsOneWidget);
    await t.tap(find.byType(PlayCta));
    expect(tapped, isFalse);
  });
}
```

- [ ] **Step 2: Implement**

```dart
// lib/presentation/widgets/play_cta.dart
import 'package:flutter/material.dart';
import '../theme/colors.dart';
import '../theme/typography.dart';

enum PlayCtaState { checking, play, unavailable }

class PlayCta extends StatelessWidget {
  const PlayCta({
    super.key,
    required this.state,
    this.label = 'Guarda',
    this.onTap,
  });

  final PlayCtaState state;
  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final isUnavailable = state == PlayCtaState.unavailable;
    final bg = isUnavailable
        ? StreamloadColors.ctaUnavailableBg
        : StreamloadColors.ctaPrimaryBg;
    final fg = isUnavailable
        ? StreamloadColors.ctaUnavailableFg
        : StreamloadColors.ctaPrimaryFg;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 250),
      child: Material(
        color: bg,
        borderRadius: BorderRadius.circular(20),
        child: InkWell(
          onTap: isUnavailable ? null : onTap,
          borderRadius: BorderRadius.circular(20),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 9),
            child: _content(fg),
          ),
        ),
      ),
    );
  }

  Widget _content(Color fg) {
    switch (state) {
      case PlayCtaState.checking:
        return SizedBox(
          width: 16,
          height: 16,
          child: CircularProgressIndicator(
              strokeWidth: 2, valueColor: AlwaysStoppedAnimation(fg)),
        );
      case PlayCtaState.play:
        return Text('▶ $label', style: StreamloadTypography.ctaLabel(color: fg));
      case PlayCtaState.unavailable:
        return Text('Al momento non disponibile',
            style: StreamloadTypography.ctaLabel(color: fg));
    }
  }
}
```

- [ ] **Step 3: Tests pass + commit**

```bash
flutter test test/widgets/play_cta_test.dart --no-pub
git add lib/presentation/widgets/play_cta.dart test/widgets/play_cta_test.dart
git commit -m "ui(widgets): PlayCta with checking/play/unavailable states (Phase A3)"
```

### Task A4: BackdropCard widget (for continue-watching)

**Files:**
- Create: `lib/presentation/widgets/cards/backdrop_card.dart`
- Test: `test/widgets/backdrop_card_test.dart`

- [ ] **Step 1: Implement**

```dart
// lib/presentation/widgets/cards/backdrop_card.dart
import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import '../../theme/colors.dart';
import '../../theme/typography.dart';

class BackdropCard extends StatelessWidget {
  const BackdropCard({
    super.key,
    required this.title,
    this.subtitle,
    this.imageUrl,
    this.progressFraction,
    this.onTap,
    this.width = 320,
  });

  final String title;
  final String? subtitle;
  final String? imageUrl;
  final double? progressFraction; // 0..1; null = no bar
  final VoidCallback? onTap;
  final double width;

  @override
  Widget build(BuildContext context) {
    final height = width * 9 / 16;
    return InkWell(
      onTap: onTap,
      child: SizedBox(
        width: width,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Stack(
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: imageUrl != null
                      ? CachedNetworkImage(
                          imageUrl: imageUrl!,
                          width: width,
                          height: height,
                          fit: BoxFit.cover,
                          placeholder: (_, __) =>
                              Container(color: StreamloadColors.surfaceGlass),
                          errorWidget: (_, __, ___) => Container(
                            color: StreamloadColors.surfaceGlass,
                            child: const Icon(Icons.movie_outlined, color: Colors.white38),
                          ),
                        )
                      : Container(
                          width: width,
                          height: height,
                          color: StreamloadColors.surfaceGlass,
                          child: const Icon(Icons.movie_outlined, color: Colors.white38),
                        ),
                ),
                if (progressFraction != null)
                  Positioned(
                    left: 0,
                    right: 0,
                    bottom: 0,
                    child: Container(
                      height: 3,
                      color: Colors.black.withValues(alpha: 0.5),
                      child: FractionallySizedBox(
                        widthFactor: progressFraction!.clamp(0.0, 1.0),
                        alignment: Alignment.centerLeft,
                        child: Container(color: Colors.white),
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 6),
            Text(title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: StreamloadTypography.body(fontSize: 12)),
            if (subtitle != null)
              Text(subtitle!,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: StreamloadTypography.metaMono()),
          ],
        ),
      ),
    );
  }
}
```

- [ ] **Step 2: Write tests** for: renders title, progress bar visible when fraction set, no progress bar when null, tap fires callback.

- [ ] **Step 3: Run tests + commit**

```bash
git add lib/presentation/widgets/cards/backdrop_card.dart test/widgets/backdrop_card_test.dart
git commit -m "ui(widgets): BackdropCard 16:9 with optional progress bar (Phase A4)"
```

### Task A5: Update PosterCard with hover scale

**Files:**
- Modify: `lib/presentation/widgets/poster_card.dart`

- [ ] **Step 1: Add `MouseRegion` + `AnimatedScale`** around the card body. On desktop, hover scales to 1.08. On phone/tablet, no hover effect.

```dart
@override
Widget build(BuildContext context) {
  final isMobile = Responsive.isMobile(context);
  return _HoverScale(
    enabled: !isMobile,
    child: InkWell(
      onTap: onTap,
      // existing SizedBox/Column body...
    ),
  );
}

class _HoverScale extends StatefulWidget {
  // small private widget that toggles scale on hover when enabled
  // ... ~30 lines
}
```

- [ ] **Step 2: Commit**

```bash
git commit -am "ui(widgets): PosterCard hover scale on desktop only (Phase A5)"
```

---

## Phase B — Navigation shell

After this phase, the app has the new top bar (desktop) + bottom tabs (phone) routing to the new routes.

### Task B1: TopNavBar with scroll-aware background

**Files:**
- Create: `lib/presentation/widgets/top_nav_bar.dart`
- Test: `test/widgets/top_nav_bar_test.dart`

- [ ] **Step 1: Implement** a `PreferredSizeWidget` with logo + nav tabs + search + avatar. Accepts a `ScrollController` (or watches a `scrollOffsetProvider`) to switch background from glass (`bgScrolled.withValues(alpha:0.85)` + blur) to solid (`bgScrolled`) once the controller's offset > 80.

```dart
// Skeleton (full impl in task)
class TopNavBar extends ConsumerWidget implements PreferredSizeWidget {
  // ...
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scrolled = ref.watch(navScrolledProvider);
    final bgColor = scrolled
        ? StreamloadColors.bgScrolled
        : StreamloadColors.bgScrolled.withValues(alpha: 0.85);
    return AnimatedContainer(
      duration: const Duration(milliseconds: 250),
      color: bgColor,
      child: ClipRect(
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
          child: SafeArea(
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 12),
              child: Row(
                children: [
                  _Logo(),
                  const SizedBox(width: 28),
                  ..._tabs(context, ref),
                  const Spacer(),
                  _SearchButton(),
                  const SizedBox(width: 12),
                  _AvatarButton(),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  Size get preferredSize => const Size.fromHeight(56);
}
```

- [ ] **Step 2: navScrolledProvider** — a `StateProvider<bool>` (or `Notifier`) flipped by a scroll listener attached in `HomePage` / `TitlePage` body scroll views.

- [ ] **Step 3: Tabs** — `Home / Film / Serie TV / Anime / La mia lista`. Active tab uses `textPrimary`; inactive `textSecondary`. Clicking navigates via `context.go(path)`.

- [ ] **Step 4: Test** background transition + tab selection.

- [ ] **Step 5: Commit**

### Task B2: AvatarMenu popover

**Files:**
- Create: `lib/presentation/widgets/avatar_menu.dart`

- [ ] **Step 1: Implement** a `PopupMenuButton` styled with glass background. Items: profile name + email (read-only header) · Impostazioni · Esci. On phone, this widget is unused — the Profilo tab replaces it.

- [ ] **Step 2: Commit**

### Task B3: Bottom tab bar for phone

**Files:**
- Create: `lib/presentation/widgets/bottom_tab_bar.dart`

- [ ] **Step 1: Implement** a 4-tab bottom navigation: Home (⌂) · Cerca (🔍) · La mia lista (☆) · Profilo (👤). Active tab highlighted. Floats over content with glass background.

```dart
class StreamloadBottomTabBar extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final current = GoRouterState.of(context).matchedLocation;
    return Container(
      decoration: BoxDecoration(
        color: StreamloadColors.bgScrolled.withValues(alpha: 0.85),
        border: Border(top: BorderSide(color: StreamloadColors.borderGlass)),
      ),
      child: ClipRect(
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceAround,
                children: [
                  _Tab(icon: Icons.home_outlined, label: 'Home', path: '/home', current: current),
                  _Tab(icon: Icons.search, label: 'Cerca', path: '/search', current: current),
                  _Tab(icon: Icons.bookmark_outline, label: 'Lista', path: '/list', current: current),
                  _Tab(icon: Icons.person_outline, label: 'Profilo', path: '/profile', current: current),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
```

- [ ] **Step 2: Commit**

### Task B4: Wire new routes + responsive shell

**Files:**
- Modify: `lib/router.dart`
- Modify: `lib/presentation/pages/app_shell.dart` (or wherever LoggedInShell lives)

- [ ] **Step 1: Add routes** `/film`, `/serie`, `/anime`, `/list`, `/search`, `/profile`.

```dart
GoRoute(path: '/film', builder: (ctx, state) => const HomePage(filter: 'movie')),
GoRoute(path: '/serie', builder: (ctx, state) => const HomePage(filter: 'tv')),
GoRoute(path: '/anime', builder: (ctx, state) => const HomePage(filter: 'anime')),
GoRoute(path: '/list', builder: (ctx, state) => const MyListPage()),
GoRoute(path: '/search', builder: (ctx, state) =>
    SearchPage(initialQuery: state.uri.queryParameters['q'] ?? '')),
GoRoute(path: '/profile', builder: (ctx, state) => const ProfilePage()),
```

Stubs for `MyListPage`, `SearchPage`, `ProfilePage` are empty `Scaffold` for now — Phase G/H fill them.

- [ ] **Step 2: AppShell** wraps every page with: `TopNavBar` on desktop/tablet, `BottomTabBar` on phone. The body fills the remaining space.

```dart
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isMobile = Responsive.isMobile(context);
    if (isMobile) {
      return Scaffold(
        backgroundColor: StreamloadColors.bgBase,
        body: child,
        bottomNavigationBar: const StreamloadBottomTabBar(),
      );
    }
    return Scaffold(
      backgroundColor: StreamloadColors.bgBase,
      body: Stack(
        children: [
          Positioned.fill(child: child),
          const Positioned(top: 0, left: 0, right: 0, child: TopNavBar()),
        ],
      ),
    );
  }
}
```

- [ ] **Step 3: Tests** for routing.

- [ ] **Step 4: Commit**

---

## Phase C — Hero infrastructure

### Task C1: Add webview_flutter dependency

**Files:**
- Modify: `pubspec.yaml`

- [ ] **Step 1:** Add deps + run pub get.

```yaml
dependencies:
  webview_flutter: ^4.10.0
  webview_flutter_wkwebview: ^3.16.0   # iOS + macOS
  webview_flutter_android: ^4.0.0       # Android
```

Run: `cd /Users/alfanowski/Desktop/Projects/Streamload-Client && flutter pub get`. macOS Podfile may need a `platform :osx, '10.15'` bump if Pods complain.

- [ ] **Step 2:** Commit `pubspec.yaml + pubspec.lock + macos/Podfile.lock`.

### Task C2: TMDB videos API

**Files:**
- Modify: `lib/data/remote/endpoints/catalog_api.dart`
- Test: `test/data/remote/catalog_api_videos_test.dart`

- [ ] **Step 1:** Add `Future<List<TmdbVideo>> videos(int tmdbId, {required String mediaType})` to `CatalogApi`. Calls backend `/api/catalog/{tmdb_id}/videos?media_type={movie|tv}` which proxies TMDB `/movie/{id}/videos` or `/tv/{id}/videos`.

```dart
// lib/domain/models/tmdb_video.dart
@freezed
class TmdbVideo with _$TmdbVideo {
  const factory TmdbVideo({
    required String key,     // youtube video id
    required String site,    // "YouTube"
    required String type,    // "Trailer" / "Teaser" / "Clip" / ...
    required bool official,
    String? name,
  }) = _TmdbVideo;
  factory TmdbVideo.fromJson(Map<String, dynamic> j) => _$TmdbVideoFromJson(j);
}

// lib/data/remote/endpoints/catalog_api.dart
Future<List<TmdbVideo>> videos(int tmdbId, {required String mediaType}) async {
  final r = await _client.raw.get<dynamic>(
    '/api/catalog/$tmdbId/videos',
    queryParameters: {'media_type': mediaType},
  );
  return ((r.data as List?) ?? const [])
      .map((j) => TmdbVideo.fromJson(j as Map<String, dynamic>))
      .toList();
}
```

Backend endpoint stub (`streamload/api/routers/catalog.py`):

```python
@router.get("/{tmdb_id}/videos")
def get_videos(tmdb_id: int, media_type: str):
    data = tmdb_client.get(f"/{media_type}/{tmdb_id}/videos")
    return [v for v in data.get("results", []) if v.get("site") == "YouTube"]
```

- [ ] **Step 2:** Test the Dart side with mocked dio.

- [ ] **Step 3:** Commit.

### Task C3: HeroTrailer widget

**Files:**
- Create: `lib/presentation/widgets/hero/hero_trailer.dart`

- [ ] **Step 1:** Implement a WebView wrapper that embeds YouTube IFrame Player API. Exposes `setMuted(bool)` via JS channel.

```dart
class HeroTrailer extends StatefulWidget {
  const HeroTrailer({super.key, required this.videoId, this.muted = true});
  final String videoId;
  final bool muted;
  @override
  State<HeroTrailer> createState() => HeroTrailerState();
}

class HeroTrailerState extends State<HeroTrailer> {
  late final WebViewController _controller;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Colors.transparent)
      ..loadHtmlString(_html(widget.videoId, widget.muted));
  }

  static String _html(String id, bool muted) => '''
<!DOCTYPE html>
<html><body style="margin:0;background:transparent;overflow:hidden;">
  <div id="p"></div>
  <script src="https://www.youtube.com/iframe_api"></script>
  <script>
    var player;
    function onYouTubeIframeAPIReady() {
      player = new YT.Player('p', {
        videoId: '$id',
        width: '100%', height: '100%',
        playerVars: {autoplay:1, mute:${muted ? 1 : 0}, controls:0, modestbranding:1, playsinline:1, rel:0, iv_load_policy:3, disablekb:1, fs:0},
        events: { 'onReady': function(e){ e.target.playVideo(); } }
      });
    }
    function setMuted(m) { if (player) m ? player.mute() : player.unMute(); }
  </script>
</body></html>
''';

  Future<void> setMuted(bool muted) =>
      _controller.runJavaScript('setMuted(${muted ? "true" : "false"})');

  @override
  Widget build(BuildContext context) =>
      WebViewWidget(controller: _controller);
}
```

- [ ] **Step 2:** Commit.

### Task C4: HeroSlide widget

**Files:**
- Create: `lib/presentation/widgets/hero/hero_slide.dart`

- [ ] **Step 1:** Implement single slide with: backdrop image (CachedNetworkImage) → HeroTrailer fades in after 2s if videoId is present → gradient overlay → label + title + meta + synopsis + CTAs + 🔊 toggle.

Layout responsive:
- Desktop: bottom-left metadata block, ~40% width
- Phone: bottom-center stacked, full-width metadata, CTAs stack vertically if width < 380.

- [ ] **Step 2:** Test with mocked data.

- [ ] **Step 3:** Commit.

### Task C5: HeroCarousel

**Files:**
- Create: `lib/presentation/widgets/hero/hero_carousel.dart`

- [ ] **Step 1:** Implement carousel of `List<HeroSlide>` items. `PageView` with auto-rotate every 30s (pause on hover/tap). Bottom-right indicator (5 dashes, active is wider). Arrow buttons on desktop hover; tap zones on mobile.

- [ ] **Step 2:** Commit.

---

## Phase D — Home page

### Task D1: Catalog rows API

**Files:**
- Create: `lib/data/remote/endpoints/catalog_rows_api.dart`
- Modify: backend `streamload/api/routers/catalog.py` to add row endpoints

- [ ] **Step 1:** Add Dart-side API:

```dart
abstract class CatalogRowsApi {
  Future<List<MediaSummary>> trendingDay();
  Future<List<MediaSummary>> trendingWeek();
  Future<List<MediaSummary>> newReleases({required String mediaType});
  Future<List<MediaSummary>> byGenre({required List<int> genreIds, required String mediaType});
  Future<List<MediaSummary>> topRated({required String mediaType});
  Future<List<MediaSummary>> similar({required int tmdbId, required String mediaType});
  Future<List<MediaSummary>> recommendations({required int tmdbId, required String mediaType});
}
```

Each method hits a corresponding backend endpoint that proxies TMDB. Backend pre-existing `catalog_api` extended with row endpoints — uses TMDB API key from env.

- [ ] **Step 2:** Implement backend endpoints. Each one is a 5-line proxy: take query, call TMDB, map fields to `MediaSummary`-compatible JSON.

- [ ] **Step 3:** Commit.

### Task D2: Row providers

**Files:**
- Create: `lib/state/home_rows_provider.dart`

- [ ] **Step 1:** Riverpod `FutureProvider`s for each row:

```dart
final trendingDayProvider = FutureProvider.autoDispose<List<MediaSummary>>((ref) async {
  final api = await ref.watch(catalogRowsApiProvider.future);
  return api.trendingDay();
});

final newReleasesProvider = FutureProvider.autoDispose
    .family<List<MediaSummary>, String>((ref, mediaType) async {
  final api = await ref.watch(catalogRowsApiProvider.future);
  return api.newReleases(mediaType: mediaType);
});
// ... similar for others
```

- [ ] **Step 2:** Commit.

### Task D3: PosterRow widget

**Files:**
- Create: `lib/presentation/widgets/rows/poster_row.dart`

- [ ] **Step 1:** Horizontal scrollable row of `PosterCard`. Header above (title + count chip + "Vedi tutti" link). Loading state = skeleton shimmer. Error state = subtle text + retry button.

```dart
class PosterRow extends StatelessWidget {
  const PosterRow({
    super.key,
    required this.title,
    required this.items,
    this.onSeeAll,
    this.onItemTap,
  });
  final String title;
  final List<MediaSummary> items;
  final VoidCallback? onSeeAll;
  final ValueChanged<MediaSummary>? onItemTap;
  // ... layout per spec
}
```

- [ ] **Step 2:** Commit.

### Task D4: BackdropRow widget (continue-watching)

**Files:**
- Create: `lib/presentation/widgets/rows/backdrop_row.dart`

- [ ] **Step 1:** Like PosterRow but uses BackdropCard. Items come from `watchProgressProvider`.

- [ ] **Step 2:** Commit.

### Task D5: HomePage rewrite

**Files:**
- Modify: `lib/presentation/pages/home_page.dart`

- [ ] **Step 1:** Compose:
  - Optional filter chips at top (only on `/film`/`/serie`/`/anime`)
  - HeroCarousel (top 5 of trendingWeek)
  - Continue Watching (BackdropRow) — hidden if empty
  - Tendenze oggi (PosterRow)
  - Nuove uscite (PosterRow)
  - Per genere · Crime & Thriller
  - Per genere · Commedie italiane
  - Anime
  - Documentari
  - La mia lista — hidden if empty
  - Visti di recente — hidden if empty
  - Top di sempre

Each PosterRow is wrapped in its own `Consumer` to load independently and not block the page.

Mobile: same rows, smaller cards. Filter chips work the same.

- [ ] **Step 2:** Scroll listener wires `navScrolledProvider` for top bar background.

- [ ] **Step 3:** Test render of the 10-row layout with mocked providers.

- [ ] **Step 4:** Commit.

---

## Phase E — Title page

### Task E1: Title page hero with backdrop+trailer

**Files:**
- Modify: `lib/presentation/pages/title_page.dart`

- [ ] **Step 1:** Replace existing header with HeroSlide (no carousel — single title). Backdrop from TMDB details; trailer from new `videos` endpoint.

- [ ] **Step 2:** Commit.

### Task E2: Cast / created-by / genres sidebar

**Files:**
- Modify: `lib/presentation/pages/title_page.dart`
- Modify: `lib/data/remote/endpoints/catalog_api.dart` (add `/credits` if not present)

- [ ] **Step 1:** Fetch credits + details. On desktop/tablet, render as right sidebar (1/3 width). On phone, render as expandable "Mostra dettagli" section below synopsis.

- [ ] **Step 2:** Commit.

### Task E3: Episode list with thumbnails

**Files:**
- Modify: `lib/presentation/pages/title_page.dart`
- Modify: episode model to include `still_path` for thumb

- [ ] **Step 1:** For TV: episode rows show 16:9 still (80×45 on phone, 120×68 on desktop) + number + title + duration. Tap → navigates to /watch with season+episode set. Use existing `episodesProvider`.

- [ ] **Step 2:** Commit.

### Task E4: Similar titles row

**Files:**
- Modify: `lib/presentation/pages/title_page.dart`

- [ ] **Step 1:** Add bottom PosterRow with `recommendationsProvider.family((tmdbId, mediaType))`. Each tap navigates to its title page.

- [ ] **Step 2:** Commit.

### Task E5: TitlePage responsive variants

- [ ] **Step 1:** LayoutBuilder branches: `_TitleDesktop`, `_TitleTablet`, `_TitleMobile`. Desktop/tablet 2-column. Mobile single column. Common widgets (hero, episode list) shared.

- [ ] **Step 2:** Commit.

---

## Phase F — Pre-check availability

### Task F1: Router.probeAvailability + cache

**Files:**
- Modify: `lib/plugins/routing/router.dart`
- Test: `test/plugins/routing/probe_availability_test.dart`

- [ ] **Step 1:** Add method to `ProviderRouter`:

```dart
/// In-memory LRU + TTL cache for availability probes.
final _probeCache = <String, _ProbeEntry>{};
static const _probeTtl = Duration(minutes: 30);

Future<bool> probeAvailability({
  required String mediaType,
  required TitleHint hint,
  int? season,
  int? episode,
}) async {
  final key = '$mediaType|${hint.title}|${hint.year}|${season ?? "-"}|${episode ?? "-"}';
  final cached = _probeCache[key];
  if (cached != null && cached.fresh) return cached.available;

  final plugins = pluginsForType(mediaType).toList();
  if (plugins.isEmpty) {
    _probeCache[key] = _ProbeEntry(false, DateTime.now());
    return false;
  }
  bool found = false;
  await Future.wait(plugins.map((p) async {
    try {
      final entry = await _resolveEntry(p, hint, mediaType);
      if (entry != null) found = true;
    } catch (_) {}
  })).timeout(const Duration(seconds: 4), onTimeout: () {});
  _probeCache[key] = _ProbeEntry(found, DateTime.now());
  return found;
}

class _ProbeEntry {
  _ProbeEntry(this.available, this.at);
  final bool available;
  final DateTime at;
  bool get fresh =>
      DateTime.now().difference(at) < ProviderRouter._probeTtl;
}
```

- [ ] **Step 2:** Tests for: caches result; returns false when no plugins; returns true if any plugin matches; respects 4s deadline.

- [ ] **Step 3:** Commit.

### Task F2: availabilityProvider

**Files:**
- Create: `lib/state/availability_provider.dart`

- [ ] **Step 1:** A `FutureProvider.family<bool, AvailabilityKey>` that calls `router.probeAvailability`. Auto-disposed.

```dart
class AvailabilityKey {
  // tmdbId, mediaType, season?, episode?
}

final availabilityProvider =
    FutureProvider.autoDispose.family<bool, AvailabilityKey>((ref, key) async {
  final controller = await ref.watch(playControllerProvider.future);
  final hint = await /* resolveTitle */;
  return controller.router.probeAvailability(
    mediaType: key.mediaType,
    hint: hint,
    season: key.season,
    episode: key.episode,
  );
});
```

- [ ] **Step 2:** Commit.

### Task F3: PlayCta wires to availabilityProvider

**Files:**
- Modify: `lib/presentation/pages/title_page.dart`

- [ ] **Step 1:** In `TitlePage`, replace direct PrimaryButton with PlayCta wrapped in a Consumer that watches `availabilityProvider(key)`. Map state:
  - `loading` → `PlayCtaState.checking`
  - `data == true` → `PlayCtaState.play` with `onTap = goToWatch`
  - `data == false || error` → `PlayCtaState.unavailable`

- [ ] **Step 2:** Commit.

---

## Phase G — Search

### Task G1: SearchOverlay widget

**Files:**
- Create: `lib/presentation/widgets/search_overlay.dart`

- [ ] **Step 1:** Fullscreen overlay. Black 85% backdrop + blur. Input top-center (22px, white caret, no border, monospace placeholder). Debounce 200ms then call TMDB `search/multi`. Show top 5 suggestions as rows (thumb + title + meta). Last item: "Mostra tutti i risultati →" (always present once query has text).

- [ ] **Step 2:** Esc closes. Click outside closes. Enter or click "Mostra tutti" → `context.go('/search?q=$query')` + close overlay.

- [ ] **Step 3:** Cmd+K shortcut binding via `Shortcuts` + `Actions` in AppShell (desktop only).

- [ ] **Step 4:** Commit.

### Task G2: SearchPage

**Files:**
- Create: `lib/presentation/pages/search_page.dart`

- [ ] **Step 1:** Implement. Input at top (always editable, updates URL via go_router on submit). Filter chip row (Tutto / Film / Serie TV / Anime). Below: grid of PosterCard via TMDB `search/multi` with type filter applied client-side. Pagination scrolls to load more.

- [ ] **Step 2:** Mobile: input takes full width of top bar area; chips wrap; grid is 2 columns.

- [ ] **Step 3:** Commit.

### Task G3: Wire mobile bottom tab

The Cerca tab in `StreamloadBottomTabBar` already navigates to `/search`. On mobile, no overlay is used — the page IS the search. The Cmd+K binding stays desktop-only.

- [ ] **Step 1:** Verify in `AppShell`: on phone, top bar is hidden; SearchPage renders standalone. On desktop, top bar 🔍 opens the overlay; SearchPage is the full grid you navigate to after.

- [ ] **Step 2:** Commit.

---

## Phase H — Settings strip

### Task H1: Remove plugin sections

**Files:**
- Modify: `lib/presentation/pages/settings_page.dart`

- [ ] **Step 1:** Delete the plugin list ListView, the "Aggiorna pacchetto plugin" button, the "Cambia token GitHub" link, and the per-row remove. Keep the page structure for the remaining sections.

- [ ] **Step 2:** Commit.

### Task H2: Add Account / Aspetto / Riproduzione / About

**Files:**
- Modify: `lib/presentation/pages/settings_page.dart`

- [ ] **Step 1:** Sections per spec:
  - **Account**: GitHub avatar + name + email (read-only). Logout button (destructive red).
  - **Aspetto**: Theme = "Scuro" (locked). Lingua = "IT" (locked). Both labeled "in arrivo".
  - **Riproduzione**: Audio preferito (dropdown, default "Italiano"), Sottotitoli preferiti (dropdown including "Disattivati", default "Disattivati"). These feed into the existing engine auto-pick logic.
  - **About**: Version (read from `pubspec.yaml` via `package_info_plus`), GitHub link, license.

- [ ] **Step 2:** A debug section visible only if a `--dart-define=DEBUG_PLUGINS=true` build flag — shows last plugin refresh time + force-refresh button + GitHub PAT status.

- [ ] **Step 3:** Commit.

---

## Phase I — Plugin onboarding restyle

### Task I1: PluginOnboardingPage tokens

**Files:**
- Modify: `lib/presentation/pages/plugin_onboarding_page.dart`

- [ ] **Step 1:** Apply new color/typography tokens. Single screen: paste PAT → verify → done. No layout changes, only token migration.

- [ ] **Step 2:** Commit.

---

## Final acceptance

- [ ] All `flutter test --no-pub` passes (target ≥ 240 tests + the new phase tests).
- [ ] `flutter analyze --no-pub` clean.
- [ ] Manual sweep at three breakpoints:
  - Desktop (≥ 1100px) — top bar + 2-column title page + hero carousel + overlay search
  - Tablet (~800px) — same as desktop with compressed layouts
  - Phone (~390px iPhone 14 width) — bottom tab bar + single column + search-as-page + gesture controls
- [ ] Operator manually verifies: hero trailer plays muted then unmutes on 🔊, "Al momento non disponibile" appears for a known-missing title, search finds Italian titles with/without accents, settings has no plugin UI.
