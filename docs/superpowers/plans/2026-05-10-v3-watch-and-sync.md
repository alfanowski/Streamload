# v3 Watch + Sync Implementation Plan (sub-plan 6b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the watch placeholder with a real player page that uses Plan #5's local proxy + media_kit to play content. Add favorites/watchlist toggles on the title page, a continue-watching row on home, and 5-second-throttled progress polling that posts to the backend.

**Architecture:** A `WatchPage` widget mounts a `media_kit_video.Video` widget connected to `playerEngineProvider` (autoDispose). On open, it asks `playController.startMovie(tmdbId)` (or `startEpisode(...)` for TV) for a proxy URL, calls `engine.open(url, headers: {})`, and starts the position stream. A `ProgressTracker` (timer + listener) watches the position stream and POSTs to `/api/progress` every 5 seconds while playing. Favorites and watchlist follow the same pattern: `StateNotifier` holds a `Set<TitleKey>` of currently-favorited items, optimistically updates on toggle, calls the backend, rolls back on failure. A new `continueWatchingProvider` fetches `/api/progress/continue-watching` and surfaces it as a `MediaRow` on the home (gated on `pluginAccess == available`).

**Tech Stack:** Flutter 3.41+, Dart 3.11+, riverpod 2.6, media_kit 1.2 + media_kit_video 1.3 (already in deps from Plan #5), dio (already), freezed 2.5.

---

## Source spec

This plan implements **sub-plan 6b** from `docs/superpowers/specs/2026-05-09-streamload-v3-design.md` §17, building on:
- **Plan #5** — `PlayController`, `PlayerEngine`, `LocalProxyServer` exist and the proxy starts at app boot. The provider wiring is in `lib/state/play_controller_provider.dart` and `lib/state/player_engine_provider.dart`.
- **Sub-plan 6a** — title page + browse UI exist. The Watch button currently navigates to `/watch/:tmdbId` which renders `WatchPlaceholderPage`.
- **OAuth + browse-only mode plan** — `pluginAccessProvider` exists. UI gates behind it.

Backend endpoints (Plan #1, all already wired in client API layer):
- `GET /api/favorites` → `[{tmdb_id, media_type, title, year, poster_url}]`
- `POST /api/favorites/{tmdb_id}?media_type=movie|tv` → 201
- `DELETE /api/favorites/{tmdb_id}?media_type=...` → 204
- Same shape for `/api/watchlist`
- `POST /api/progress {tmdb_id, media_type, season_number?, episode_number?, position_seconds, duration_seconds}`
- `GET /api/progress/continue-watching` → `{items: [...]}`

The terminal state of this plan is: from a populated home, tap Breaking Bad poster → title page → tap an episode → `/watch/1396?media_type=tv&season=1&episode=1` → player loads (or shows error if no plugin can satisfy the title) → user plays for 30s → app POSTs progress every 5s → user closes player → returns to title page → next opening of home shows Breaking Bad in "Continua a guardare". Favorites and watchlist toggles work from the title page header and the items appear in dedicated provider streams (Library tabs reading them is out of scope — sub-plan 6c).

## Out of scope for 6b

- Library tabs for "Preferiti" / "Watchlist" (the data is fetched and the toggle works; the dedicated UI is 6c polish)
- Skip-intro / chapters (post-MVP per §16)
- Subtitles in HLS (post-MVP per §16)
- AirPlay / Cast output (post-MVP per §16)
- Watch history detail page
- Telemetry batching (sub-plan 6c)
- Auto-updater + build pipeline (sub-plan 6c)

---

## File structure

### New files

| Path | Created in | Purpose |
|---|---|---|
| `lib/presentation/pages/watch_page.dart` | T2 | replaces `WatchPlaceholderPage`; mounts media_kit Video + custom controls |
| `lib/presentation/widgets/player_controls.dart` | T3 | overlay: play/pause, scrub bar, time, close button |
| `lib/presentation/widgets/favorite_button.dart` | T6 | heart icon — reads + writes `favoritesProvider` |
| `lib/presentation/widgets/watchlist_button.dart` | T6 | bookmark icon — reads + writes `watchlistProvider` |
| `lib/state/favorites_provider.dart` | T5 | `Set<TitleKey>` + optimistic toggle |
| `lib/state/watchlist_provider.dart` | T5 | same pattern |
| `lib/state/progress_tracker.dart` | T8 | listens to player position; POSTs every 5s |
| `lib/state/continue_watching_provider.dart` | T9 | wraps continueWatchingApi |
| `lib/domain/models/title_key.dart` | T5 | `class TitleKey { tmdbId, mediaType }` |
| `lib/domain/models/continue_watching_item.dart` | T9 | freezed DTO |
| `lib/domain/models/playback_request.dart` | T2 | freezed `PlaybackRequest{tmdbId, mediaType, season?, episode?}` |
| `test/pages/watch_page_test.dart` | T2 | mock controller + engine, assert lifecycle |
| `test/widgets/player_controls_test.dart` | T3 | tap play → callback fires |
| `test/widgets/favorite_button_test.dart` | T6 | toggle calls api + flips state |
| `test/state/favorites_provider_test.dart` | T5 | optimistic + rollback on api failure |
| `test/state/watchlist_provider_test.dart` | T5 | same |
| `test/state/progress_tracker_test.dart` | T8 | fake position stream + assert post calls |
| `test/state/continue_watching_provider_test.dart` | T9 | mock api + parse |

### Modified files

| Path | Modified in | Change |
|---|---|---|
| `lib/router.dart` | T4 | swap `WatchPlaceholderPage` → `WatchPage` |
| `lib/presentation/pages/title_page.dart` | T7 | add favorite + watchlist buttons in the AppBar actions for both movie + TV variants |
| `lib/presentation/pages/home_page.dart` | T10 | prepend a "Continua a guardare" `MediaRow` when `pluginAccess == available` and the list is non-empty |
| `lib/presentation/pages/watch_placeholder_page.dart` | T4 | DELETED |
| `test/pages/watch_placeholder_page_test.dart` | T4 | DELETED if exists |

---

## Phase A — Watch page + player controls

### Task 1: `PlaybackRequest` model + helper for resolving the proxy URL

**Files:**
- Create: `lib/domain/models/playback_request.dart`

- [ ] **Step 1: freezed model**

```dart
// lib/domain/models/playback_request.dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'playback_request.freezed.dart';

@freezed
class PlaybackRequest with _$PlaybackRequest {
  const factory PlaybackRequest({
    required int tmdbId,
    required String mediaType,
    int? season,
    int? episode,
  }) = _PlaybackRequest;
}
```

- [ ] **Step 2: codegen + commit (no tests — pure DTO, exercised by Task 2)**

```bash
dart run build_runner build --delete-conflicting-outputs
git add lib/domain/models/playback_request.dart lib/domain/models/playback_request.freezed.dart
git commit -m "model: PlaybackRequest DTO for the watch page"
```

---

### Task 2: `WatchPage` shell

**Files:**
- Create: `lib/presentation/pages/watch_page.dart`
- Create: `test/pages/watch_page_test.dart`

The page does, on initState:
1. `await ref.read(playControllerProvider.future)` → `PlayController`
2. Call `controller.startMovie(tmdbId)` or `startEpisode(...)` based on PlaybackRequest
3. On success → `engine.open(url, headers: const {})` + `engine.play()`
4. Track loading + error states; render Video widget once playing
5. On dispose → `engine.pause()` (engine itself is autoDispose so it'll clean up)

For now the controls are a separate widget (Task 3) — this task just gets the video on screen.

- [ ] **Step 1: Write the failing widget test**

```dart
// test/pages/watch_page_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/domain/models/playback_request.dart';
import 'package:streamload_client/domain/play_title.dart';
import 'package:streamload_client/player/engine.dart';
import 'package:streamload_client/presentation/pages/watch_page.dart';
import 'package:streamload_client/state/play_controller_provider.dart';
import 'package:streamload_client/state/player_engine_provider.dart';

class _ControllerMock extends Mock implements PlayController {}
class _EngineMock extends Mock implements PlayerEngine {}

void main() {
  setUpAll(() {
    registerFallbackValue(const Duration());
  });

  testWidgets('on mount calls startMovie + engine.open + play', (tester) async {
    final controller = _ControllerMock();
    final engine = _EngineMock();
    when(() => controller.startMovie(tmdbId: 42))
        .thenAnswer((_) async => 'http://127.0.0.1:9999/master/abc.m3u8');
    when(() => engine.open(any(), headers: any(named: 'headers')))
        .thenAnswer((_) {});
    when(engine.play).thenAnswer((_) async {});

    await tester.pumpWidget(ProviderScope(
      overrides: [
        playControllerProvider.overrideWith((_) async => controller),
        playerEngineProvider.overrideWith((_) => engine),
      ],
      child: const MaterialApp(home: WatchPage(
        request: PlaybackRequest(tmdbId: 42, mediaType: 'movie'),
      )),
    ));
    await tester.pumpAndSettle();

    verify(() => controller.startMovie(tmdbId: 42)).called(1);
    verify(() => engine.open(
          'http://127.0.0.1:9999/master/abc.m3u8',
          headers: const {},
        )).called(1);
    verify(engine.play).called(1);
  });

  testWidgets('startEpisode used for TV requests', (tester) async {
    final controller = _ControllerMock();
    final engine = _EngineMock();
    when(() => controller.startEpisode(tmdbId: 1, season: 1, episode: 1))
        .thenAnswer((_) async => 'http://127.0.0.1:9999/master/xyz.m3u8');
    when(() => engine.open(any(), headers: any(named: 'headers')))
        .thenAnswer((_) {});
    when(engine.play).thenAnswer((_) async {});

    await tester.pumpWidget(ProviderScope(
      overrides: [
        playControllerProvider.overrideWith((_) async => controller),
        playerEngineProvider.overrideWith((_) => engine),
      ],
      child: const MaterialApp(home: WatchPage(
        request: PlaybackRequest(
          tmdbId: 1, mediaType: 'tv', season: 1, episode: 1,
        ),
      )),
    ));
    await tester.pumpAndSettle();

    verify(() => controller.startEpisode(tmdbId: 1, season: 1, episode: 1))
        .called(1);
  });

  testWidgets('error state shown when startMovie throws', (tester) async {
    final controller = _ControllerMock();
    final engine = _EngineMock();
    when(() => controller.startMovie(tmdbId: 1))
        .thenThrow(StateError('no plugin available'));

    await tester.pumpWidget(ProviderScope(
      overrides: [
        playControllerProvider.overrideWith((_) async => controller),
        playerEngineProvider.overrideWith((_) => engine),
      ],
      child: const MaterialApp(home: WatchPage(
        request: PlaybackRequest(tmdbId: 1, mediaType: 'movie'),
      )),
    ));
    await tester.pumpAndSettle();

    expect(find.textContaining('no plugin available'), findsOneWidget);
  });
}
```

- [ ] **Step 2: Implement the page**

```dart
// lib/presentation/pages/watch_page.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:media_kit_video/media_kit_video.dart';

import '../../domain/models/playback_request.dart';
import '../../state/play_controller_provider.dart';
import '../../state/player_engine_provider.dart';
import '../theme/colors.dart';
import '../theme/typography.dart';
import '../widgets/player_controls.dart';

class WatchPage extends ConsumerStatefulWidget {
  const WatchPage({super.key, required this.request});
  final PlaybackRequest request;

  @override
  ConsumerState<WatchPage> createState() => _WatchPageState();
}

enum _Phase { loading, playing, error }

class _WatchPageState extends ConsumerState<WatchPage> {
  _Phase _phase = _Phase.loading;
  String? _error;
  late final VideoController _videoController;

  @override
  void initState() {
    super.initState();
    final engine = ref.read(playerEngineProvider);
    _videoController = VideoController(engine.player);
    WidgetsBinding.instance.addPostFrameCallback((_) => _start());
  }

  Future<void> _start() async {
    try {
      final controller = await ref.read(playControllerProvider.future);
      final url = widget.request.season != null && widget.request.episode != null
          ? await controller.startEpisode(
              tmdbId: widget.request.tmdbId,
              season: widget.request.season!,
              episode: widget.request.episode!,
            )
          : await controller.startMovie(tmdbId: widget.request.tmdbId);
      final engine = ref.read(playerEngineProvider);
      engine.open(url, headers: const {});
      await engine.play();
      if (mounted) setState(() => _phase = _Phase.playing);
    } catch (e) {
      if (mounted) {
        setState(() {
          _phase = _Phase.error;
          _error = e.toString();
        });
      }
    }
  }

  @override
  void dispose() {
    // Pause on close — autoDispose will tear down the engine itself.
    ref.read(playerEngineProvider).pause();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Stack(
          children: [
            switch (_phase) {
              _Phase.loading => const Center(child: CircularProgressIndicator()),
              _Phase.error => Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      _error ?? 'Errore sconosciuto',
                      textAlign: TextAlign.center,
                      style: StreamloadTypography.body(
                          fontSize: 14, color: StreamloadColors.critical),
                    ),
                  ),
                ),
              _Phase.playing => Video(controller: _videoController),
            },
            // Always-visible top bar with close.
            Positioned(
              top: 8, left: 8,
              child: IconButton(
                icon: const Icon(Icons.close, color: Colors.white),
                onPressed: () => context.pop(),
                tooltip: 'Chiudi',
              ),
            ),
            // Bottom controls overlay only when playing.
            if (_phase == _Phase.playing)
              const Positioned(
                left: 0, right: 0, bottom: 0,
                child: PlayerControls(),
              ),
          ],
        ),
      ),
    );
  }
}
```

- [ ] **Step 3: Run tests, expect 3 pass**

> media_kit's VideoController + Video may need `MediaKit.ensureInitialized()` already called. The `playerEngineProvider` does this in its body (Plan #5 wiring). For tests with the mocked engine, the Video widget won't render but `pumpAndSettle` should handle it. If `Video` throws in tests because the real player isn't there, gate the widget behind a `kIsWeb || mocked` check OR provide a fake VideoController via a dependency.

For test simplicity: extract a `_VideoBuilder` typedef parameter on WatchPage with a default that constructs Video, and override it in tests:

```dart
typedef VideoBuilder = Widget Function(VideoController controller);

class WatchPage extends ConsumerStatefulWidget {
  const WatchPage({
    super.key,
    required this.request,
    this.videoBuilder = _defaultVideoBuilder,
  });
  final PlaybackRequest request;
  final VideoBuilder videoBuilder;
}

Widget _defaultVideoBuilder(VideoController c) => Video(controller: c);
```

Tests pass `(c) => SizedBox.shrink()` to skip the real Video widget.

- [ ] **Step 4: Commit**

```bash
git add lib/presentation/pages/watch_page.dart test/pages/watch_page_test.dart
git commit -m "pages: WatchPage — wires PlayController + PlayerEngine to media_kit Video"
```

---

### Task 3: `PlayerControls` overlay

**Files:**
- Create: `lib/presentation/widgets/player_controls.dart`
- Create: `test/widgets/player_controls_test.dart`

Bottom-anchored overlay with: ◉ play/pause toggle, ◉ position label, ◉ scrub Slider, ◉ duration label. Reads streams from `playerEngineProvider`. Uses `engine.seek(Duration)` on slider drag end.

- [ ] **Step 1: Failing widget test**

```dart
// test/widgets/player_controls_test.dart
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/player/engine.dart';
import 'package:streamload_client/presentation/widgets/player_controls.dart';
import 'package:streamload_client/state/player_engine_provider.dart';

class _EngineMock extends Mock implements PlayerEngine {}

void main() {
  testWidgets('shows play icon when not playing, tap calls play()', (tester) async {
    final engine = _EngineMock();
    final positionCtrl = StreamController<Duration>.broadcast();
    final durationCtrl = StreamController<Duration>.broadcast();
    final playingCtrl = StreamController<bool>.broadcast();
    when(() => engine.positionStream).thenAnswer((_) => positionCtrl.stream);
    when(() => engine.durationStream).thenAnswer((_) => durationCtrl.stream);
    when(() => engine.playingStream).thenAnswer((_) => playingCtrl.stream);
    when(engine.play).thenAnswer((_) async {});

    await tester.pumpWidget(ProviderScope(
      overrides: [playerEngineProvider.overrideWith((_) => engine)],
      child: const MaterialApp(
        home: Scaffold(body: PlayerControls()),
      ),
    ));
    playingCtrl.add(false);
    durationCtrl.add(const Duration(seconds: 60));
    await tester.pumpAndSettle();

    expect(find.byIcon(Icons.play_arrow), findsOneWidget);
    await tester.tap(find.byIcon(Icons.play_arrow));
    verify(engine.play).called(1);

    await positionCtrl.close();
    await durationCtrl.close();
    await playingCtrl.close();
  });
}
```

- [ ] **Step 2: Implement**

```dart
// lib/presentation/widgets/player_controls.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/player_engine_provider.dart';

class PlayerControls extends ConsumerWidget {
  const PlayerControls({super.key});

  static String _fmt(Duration d) {
    final h = d.inHours;
    final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return h > 0 ? '$h:$m:$s' : '$m:$s';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final engine = ref.watch(playerEngineProvider);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Colors.transparent, Colors.black.withValues(alpha: 0.85)],
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Scrub bar
          StreamBuilder<Duration>(
            stream: engine.positionStream,
            builder: (_, posSnap) {
              return StreamBuilder<Duration>(
                stream: engine.durationStream,
                builder: (_, durSnap) {
                  final pos = posSnap.data ?? Duration.zero;
                  final dur = durSnap.data ?? Duration.zero;
                  final maxMs = dur.inMilliseconds.clamp(1, 1 << 31);
                  return Row(
                    children: [
                      Text(_fmt(pos),
                          style: const TextStyle(
                              color: Colors.white, fontSize: 12)),
                      Expanded(
                        child: Slider(
                          value: pos.inMilliseconds
                              .clamp(0, maxMs)
                              .toDouble(),
                          max: maxMs.toDouble(),
                          onChangeEnd: (v) =>
                              engine.seek(Duration(milliseconds: v.toInt())),
                          onChanged: (_) {},
                        ),
                      ),
                      Text(_fmt(dur),
                          style: const TextStyle(
                              color: Colors.white, fontSize: 12)),
                    ],
                  );
                },
              );
            },
          ),
          const SizedBox(height: 4),
          // Play/pause
          StreamBuilder<bool>(
            stream: engine.playingStream,
            builder: (_, snap) {
              final playing = snap.data ?? false;
              return IconButton(
                iconSize: 40,
                color: Colors.white,
                icon: Icon(playing ? Icons.pause : Icons.play_arrow),
                onPressed: () => playing ? engine.pause() : engine.play(),
              );
            },
          ),
        ],
      ),
    );
  }
}
```

- [ ] **Step 3: Run + commit**

```bash
git add lib/presentation/widgets/player_controls.dart test/widgets/player_controls_test.dart
git commit -m "widgets: PlayerControls overlay (play/pause + scrub + time)"
```

---

### Task 4: Router swap — drop placeholder, mount real WatchPage

**Files:**
- Modify: `lib/router.dart`
- Delete: `lib/presentation/pages/watch_placeholder_page.dart`
- Delete: `test/pages/watch_placeholder_page_test.dart` if exists

- [ ] **Step 1: Replace the route**

```dart
GoRoute(
  path: '/watch/:tmdbId',
  builder: (ctx, state) => WatchPage(
    request: PlaybackRequest(
      tmdbId: int.parse(state.pathParameters['tmdbId']!),
      mediaType: state.uri.queryParameters['media_type'] ?? 'movie',
      season: int.tryParse(state.uri.queryParameters['season'] ?? ''),
      episode: int.tryParse(state.uri.queryParameters['episode'] ?? ''),
    ),
  ),
),
```

Drop the `watch_placeholder_page.dart` import; add `watch_page.dart` and `playback_request.dart`.

- [ ] **Step 2: `git rm` placeholder + commit**

```bash
git rm lib/presentation/pages/watch_placeholder_page.dart
[ -f test/pages/watch_placeholder_page_test.dart ] && git rm test/pages/watch_placeholder_page_test.dart || true
git add lib/router.dart
git commit -m "router: WatchPage replaces WatchPlaceholderPage"
```

---

## Phase B — Favorites + Watchlist

### Task 5: Provider + storage for favorites and watchlist

**Files:**
- Create: `lib/domain/models/title_key.dart`
- Create: `lib/state/favorites_provider.dart`
- Create: `lib/state/watchlist_provider.dart`
- Create: `test/state/favorites_provider_test.dart`
- Create: `test/state/watchlist_provider_test.dart`

- [ ] **Step 1: TitleKey value type**

```dart
// lib/domain/models/title_key.dart
class TitleKey {
  const TitleKey({required this.tmdbId, required this.mediaType});
  final int tmdbId;
  final String mediaType;

  @override
  bool operator ==(Object other) =>
      other is TitleKey &&
      other.tmdbId == tmdbId &&
      other.mediaType == mediaType;
  @override
  int get hashCode => Object.hash(tmdbId, mediaType);
}
```

- [ ] **Step 2: Failing test for favorites (mirror for watchlist)**

```dart
// test/state/favorites_provider_test.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/favorites_api.dart';
import 'package:streamload_client/domain/models/title_key.dart';
import 'package:streamload_client/state/favorites_provider.dart';

class _FavApiMock extends Mock implements FavoritesApi {}

void main() {
  late _FavApiMock api;
  setUp(() {
    api = _FavApiMock();
    when(api.list).thenAnswer((_) async => [
      {'tmdb_id': 1, 'media_type': 'movie', 'title': 'Dune', 'year': 2021,
       'poster_url': null},
    ]);
  });

  test('initial load populates set from backend', () async {
    final c = ProviderContainer(overrides: [
      favoritesApiProvider.overrideWith((_) async => api),
    ]);
    addTearDown(c.dispose);
    final state = await c.read(favoritesProvider.future);
    expect(state.contains(const TitleKey(tmdbId: 1, mediaType: 'movie')), isTrue);
  });

  test('toggle adds optimistically + calls api.add', () async {
    when(() => api.add(tmdbId: 5, mediaType: 'movie'))
        .thenAnswer((_) async {});
    final c = ProviderContainer(overrides: [
      favoritesApiProvider.overrideWith((_) async => api),
    ]);
    addTearDown(c.dispose);
    await c.read(favoritesProvider.future);
    await c.read(favoritesProvider.notifier).toggle(
      const TitleKey(tmdbId: 5, mediaType: 'movie'),
    );
    final state = c.read(favoritesProvider).value!;
    expect(state.contains(const TitleKey(tmdbId: 5, mediaType: 'movie')), isTrue);
    verify(() => api.add(tmdbId: 5, mediaType: 'movie')).called(1);
  });

  test('toggle on existing item removes via api.remove', () async {
    when(() => api.remove(tmdbId: 1, mediaType: 'movie'))
        .thenAnswer((_) async {});
    final c = ProviderContainer(overrides: [
      favoritesApiProvider.overrideWith((_) async => api),
    ]);
    addTearDown(c.dispose);
    await c.read(favoritesProvider.future);
    await c.read(favoritesProvider.notifier).toggle(
      const TitleKey(tmdbId: 1, mediaType: 'movie'),
    );
    final state = c.read(favoritesProvider).value!;
    expect(state.contains(const TitleKey(tmdbId: 1, mediaType: 'movie')), isFalse);
  });

  test('rolls back optimistic add when api throws', () async {
    when(() => api.add(tmdbId: 5, mediaType: 'movie'))
        .thenThrow(Exception('boom'));
    final c = ProviderContainer(overrides: [
      favoritesApiProvider.overrideWith((_) async => api),
    ]);
    addTearDown(c.dispose);
    await c.read(favoritesProvider.future);
    await expectLater(
      c.read(favoritesProvider.notifier).toggle(
        const TitleKey(tmdbId: 5, mediaType: 'movie'),
      ),
      throwsException,
    );
    final state = c.read(favoritesProvider).value!;
    expect(state.contains(const TitleKey(tmdbId: 5, mediaType: 'movie')), isFalse);
  });
}
```

- [ ] **Step 3: Implement favorites_provider**

```dart
// lib/state/favorites_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/models/title_key.dart';
import 'api_client_provider.dart';

class FavoritesNotifier extends AsyncNotifier<Set<TitleKey>> {
  @override
  Future<Set<TitleKey>> build() async {
    final api = await ref.watch(favoritesApiProvider.future);
    final items = await api.list();
    return items
        .map((e) => TitleKey(
              tmdbId: e['tmdb_id'] as int,
              mediaType: e['media_type'] as String,
            ))
        .toSet();
  }

  Future<void> toggle(TitleKey key) async {
    final current = state.value ?? <TitleKey>{};
    final isCurrentlyFavorite = current.contains(key);
    // Optimistic update.
    final next = Set<TitleKey>.from(current);
    if (isCurrentlyFavorite) {
      next.remove(key);
    } else {
      next.add(key);
    }
    state = AsyncData(next);

    try {
      final api = await ref.read(favoritesApiProvider.future);
      if (isCurrentlyFavorite) {
        await api.remove(tmdbId: key.tmdbId, mediaType: key.mediaType);
      } else {
        await api.add(tmdbId: key.tmdbId, mediaType: key.mediaType);
      }
    } catch (_) {
      // Roll back.
      state = AsyncData(current);
      rethrow;
    }
  }
}

final favoritesProvider =
    AsyncNotifierProvider<FavoritesNotifier, Set<TitleKey>>(
  FavoritesNotifier.new,
);
```

The watchlist provider is identical with `WatchlistApi` substituted. Copy the file, rename FavoritesNotifier → WatchlistNotifier, favoritesApiProvider → watchlistApiProvider.

> Verify the existing `FavoritesApi` and `WatchlistApi` shapes (`lib/data/remote/endpoints/favorites_api.dart`, `watchlist_api.dart`) — adjust method signatures if they differ from `add(tmdbId:, mediaType:)` / `remove(tmdbId:, mediaType:)` / `list() → List<Map<String, dynamic>>`. Also confirm `favoritesApiProvider` and `watchlistApiProvider` exist in `api_client_provider.dart`.

- [ ] **Step 4: Run tests + commit**

```bash
git add lib/domain/models/title_key.dart lib/state/favorites_provider.dart \
        lib/state/watchlist_provider.dart \
        test/state/favorites_provider_test.dart \
        test/state/watchlist_provider_test.dart
git commit -m "state: favoritesProvider + watchlistProvider with optimistic toggle + rollback"
```

---

### Task 6: `FavoriteButton` + `WatchlistButton` widgets

**Files:**
- Create: `lib/presentation/widgets/favorite_button.dart`
- Create: `lib/presentation/widgets/watchlist_button.dart`
- Create: `test/widgets/favorite_button_test.dart`

- [ ] **Step 1: Failing test for FavoriteButton**

```dart
// test/widgets/favorite_button_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/favorites_api.dart';
import 'package:streamload_client/domain/models/title_key.dart';
import 'package:streamload_client/presentation/widgets/favorite_button.dart';
import 'package:streamload_client/state/favorites_provider.dart';
import 'package:streamload_client/state/api_client_provider.dart';

class _FavApiMock extends Mock implements FavoritesApi {}

void main() {
  testWidgets('renders outline when not favorited; tap calls api.add', (tester) async {
    final api = _FavApiMock();
    when(api.list).thenAnswer((_) async => []);
    when(() => api.add(tmdbId: 7, mediaType: 'movie')).thenAnswer((_) async {});

    await tester.pumpWidget(ProviderScope(
      overrides: [favoritesApiProvider.overrideWith((_) async => api)],
      child: const MaterialApp(
        home: Scaffold(body: Center(child: FavoriteButton(
          target: TitleKey(tmdbId: 7, mediaType: 'movie'),
        ))),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.byIcon(Icons.favorite_border), findsOneWidget);
    await tester.tap(find.byIcon(Icons.favorite_border));
    await tester.pumpAndSettle();
    verify(() => api.add(tmdbId: 7, mediaType: 'movie')).called(1);
    expect(find.byIcon(Icons.favorite), findsOneWidget);
  });
}
```

- [ ] **Step 2: Implement**

```dart
// lib/presentation/widgets/favorite_button.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/models/title_key.dart';
import '../../state/favorites_provider.dart';

class FavoriteButton extends ConsumerWidget {
  const FavoriteButton({super.key, required this.target});
  final TitleKey target;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(favoritesProvider);
    final isFavorite = state.maybeWhen(
      data: (set) => set.contains(target),
      orElse: () => false,
    );
    return IconButton(
      tooltip: isFavorite ? 'Rimuovi dai preferiti' : 'Aggiungi ai preferiti',
      icon: Icon(isFavorite ? Icons.favorite : Icons.favorite_border),
      color: isFavorite ? Colors.redAccent : null,
      onPressed: state.isLoading
          ? null
          : () async {
              try {
                await ref.read(favoritesProvider.notifier).toggle(target);
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Errore: $e')),
                  );
                }
              }
            },
    );
  }
}
```

`WatchlistButton` is the same, swapping `favoritesProvider` ↔ `watchlistProvider` and `Icons.favorite{,_border}` ↔ `Icons.bookmark{,_border}`.

- [ ] **Step 3: Run + commit**

```bash
git add lib/presentation/widgets/favorite_button.dart \
        lib/presentation/widgets/watchlist_button.dart \
        test/widgets/favorite_button_test.dart
git commit -m "widgets: FavoriteButton + WatchlistButton with optimistic toggle"
```

---

### Task 7: Wire favorite + watchlist buttons into TitlePage AppBar

**Files:**
- Modify: `lib/presentation/pages/title_page.dart`

- [ ] **Step 1: Add the two buttons to the AppBar's `actions:` for both movie and TV variants**

The existing TitlePage shell builds the AppBar at the top. Update the AppBar:

```dart
appBar: AppBar(
  actions: [
    FavoriteButton(target: TitleKey(tmdbId: tmdbId, mediaType: mediaType)),
    WatchlistButton(target: TitleKey(tmdbId: tmdbId, mediaType: mediaType)),
    const SizedBox(width: 8),
  ],
),
```

> The AppBar lives in the outer `TitlePage.build` (not inside the inner movie/TV bodies) — confirm by reading the file. If movie + TV have separate AppBars, add to both.

- [ ] **Step 2: Run full suite, expect green**

- [ ] **Step 3: Commit**

```bash
git add lib/presentation/pages/title_page.dart
git commit -m "pages: TitlePage AppBar adds FavoriteButton + WatchlistButton"
```

---

## Phase C — Progress + Continue Watching

### Task 8: `ProgressTracker` — listens to position, posts to backend every 5s

**Files:**
- Create: `lib/state/progress_tracker.dart`
- Create: `test/state/progress_tracker_test.dart`

- [ ] **Step 1: Failing test using `fake_async`**

```dart
// test/state/progress_tracker_test.dart
import 'dart:async';
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/progress_api.dart';
import 'package:streamload_client/state/progress_tracker.dart';

class _ProgressApiMock extends Mock implements ProgressApi {}

void main() {
  setUpAll(() {
    registerFallbackValue(const Duration());
  });

  test('emits POST /progress every 5 seconds while position advances', () {
    fakeAsync((async) {
      final api = _ProgressApiMock();
      when(() => api.post(
            tmdbId: any(named: 'tmdbId'),
            mediaType: any(named: 'mediaType'),
            season: any(named: 'season'),
            episode: any(named: 'episode'),
            positionSeconds: any(named: 'positionSeconds'),
            durationSeconds: any(named: 'durationSeconds'),
          )).thenAnswer((_) async {});

      final positionCtrl = StreamController<Duration>.broadcast();
      final durationCtrl = StreamController<Duration>.broadcast();
      durationCtrl.add(const Duration(seconds: 600));

      final tracker = ProgressTracker(
        api: api,
        tmdbId: 1, mediaType: 'movie',
        positionStream: positionCtrl.stream,
        durationStream: durationCtrl.stream,
        flushInterval: const Duration(seconds: 5),
      );
      tracker.start();

      positionCtrl.add(const Duration(seconds: 10));
      async.elapse(const Duration(seconds: 6));
      verify(() => api.post(
            tmdbId: 1, mediaType: 'movie',
            season: null, episode: null,
            positionSeconds: 10, durationSeconds: 600,
          )).called(1);

      positionCtrl.add(const Duration(seconds: 30));
      async.elapse(const Duration(seconds: 6));
      verify(() => api.post(
            tmdbId: 1, mediaType: 'movie',
            season: null, episode: null,
            positionSeconds: 30, durationSeconds: 600,
          )).called(1);

      tracker.stop();
    });
  });

  test('does not flush when position is unchanged since last flush', () {
    fakeAsync((async) {
      final api = _ProgressApiMock();
      when(() => api.post(
            tmdbId: any(named: 'tmdbId'),
            mediaType: any(named: 'mediaType'),
            season: any(named: 'season'),
            episode: any(named: 'episode'),
            positionSeconds: any(named: 'positionSeconds'),
            durationSeconds: any(named: 'durationSeconds'),
          )).thenAnswer((_) async {});

      final positionCtrl = StreamController<Duration>.broadcast();
      final durationCtrl = StreamController<Duration>.broadcast();
      durationCtrl.add(const Duration(seconds: 600));

      final tracker = ProgressTracker(
        api: api,
        tmdbId: 1, mediaType: 'movie',
        positionStream: positionCtrl.stream,
        durationStream: durationCtrl.stream,
        flushInterval: const Duration(seconds: 5),
      );
      tracker.start();

      positionCtrl.add(const Duration(seconds: 10));
      async.elapse(const Duration(seconds: 6)); // 1 flush
      async.elapse(const Duration(seconds: 6)); // no new position → no flush
      verify(() => api.post(
            tmdbId: any(named: 'tmdbId'),
            mediaType: any(named: 'mediaType'),
            season: any(named: 'season'),
            episode: any(named: 'episode'),
            positionSeconds: any(named: 'positionSeconds'),
            durationSeconds: any(named: 'durationSeconds'),
          )).called(1);

      tracker.stop();
    });
  });
}
```

- [ ] **Step 2: Implement**

```dart
// lib/state/progress_tracker.dart
import 'dart:async';

import '../data/remote/endpoints/progress_api.dart';

class ProgressTracker {
  ProgressTracker({
    required this.api,
    required this.tmdbId,
    required this.mediaType,
    required this.positionStream,
    required this.durationStream,
    this.season,
    this.episode,
    this.flushInterval = const Duration(seconds: 5),
  });

  final ProgressApi api;
  final int tmdbId;
  final String mediaType;
  final int? season;
  final int? episode;
  final Stream<Duration> positionStream;
  final Stream<Duration> durationStream;
  final Duration flushInterval;

  StreamSubscription<Duration>? _posSub;
  StreamSubscription<Duration>? _durSub;
  Timer? _flushTimer;
  Duration _lastSeen = Duration.zero;
  Duration _lastFlushed = const Duration(seconds: -1);
  Duration _duration = Duration.zero;

  void start() {
    _posSub = positionStream.listen((d) => _lastSeen = d);
    _durSub = durationStream.listen((d) => _duration = d);
    _flushTimer = Timer.periodic(flushInterval, (_) => _flush());
  }

  Future<void> _flush() async {
    if (_lastSeen == _lastFlushed) return;
    if (_duration <= Duration.zero) return;
    final pos = _lastSeen;
    final dur = _duration;
    try {
      await api.post(
        tmdbId: tmdbId,
        mediaType: mediaType,
        season: season,
        episode: episode,
        positionSeconds: pos.inSeconds,
        durationSeconds: dur.inSeconds,
      );
      _lastFlushed = pos;
    } catch (_) {
      // swallow — next tick retries.
    }
  }

  void stop() {
    _flushTimer?.cancel();
    _posSub?.cancel();
    _durSub?.cancel();
    // Best-effort final flush.
    _flush();
  }
}
```

> Confirm the existing `ProgressApi.post(...)` signature in `lib/data/remote/endpoints/progress_api.dart`. If it differs (e.g. positional args or different param names), adjust both the tracker call and the test mock.

- [ ] **Step 3: Wire into WatchPage** — in `_State`:

```dart
ProgressTracker? _tracker;
// In _start() after engine.play():
_tracker = ProgressTracker(
  api: await ref.read(progressApiProvider.future),
  tmdbId: widget.request.tmdbId,
  mediaType: widget.request.mediaType,
  season: widget.request.season,
  episode: widget.request.episode,
  positionStream: ref.read(playerEngineProvider).positionStream,
  durationStream: ref.read(playerEngineProvider).durationStream,
)..start();

// In dispose():
_tracker?.stop();
```

- [ ] **Step 4: Run + commit**

```bash
git add lib/state/progress_tracker.dart test/state/progress_tracker_test.dart \
        lib/presentation/pages/watch_page.dart
git commit -m "state: ProgressTracker — 5s-throttled POST /api/progress wired into WatchPage"
```

---

### Task 9: `continueWatchingProvider` + DTO

**Files:**
- Create: `lib/domain/models/continue_watching_item.dart`
- Create: `lib/state/continue_watching_provider.dart`
- Create: `test/state/continue_watching_provider_test.dart`

- [ ] **Step 1: freezed DTO matching backend ContinueWatchingResponse / ProgressItem**

```dart
// lib/domain/models/continue_watching_item.dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'continue_watching_item.freezed.dart';
part 'continue_watching_item.g.dart';

@freezed
class ContinueWatchingItem with _$ContinueWatchingItem {
  const factory ContinueWatchingItem({
    @JsonKey(name: 'tmdb_id') required int tmdbId,
    @JsonKey(name: 'media_type') required String mediaType,
    required String title,
    int? year,
    @JsonKey(name: 'poster_url') String? posterUrl,
    @JsonKey(name: 'season_number') int? seasonNumber,
    @JsonKey(name: 'episode_number') int? episodeNumber,
    @JsonKey(name: 'position_seconds') required int positionSeconds,
    @JsonKey(name: 'duration_seconds') required int durationSeconds,
  }) = _ContinueWatchingItem;

  factory ContinueWatchingItem.fromJson(Map<String, dynamic> json) =>
      _$ContinueWatchingItemFromJson(json);
}
```

> Read `streamload/api/routes/progress.py` ProgressItem to confirm field names — adjust `@JsonKey` mappings if they differ.

- [ ] **Step 2: Provider**

```dart
// lib/state/continue_watching_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/models/continue_watching_item.dart';
import 'api_client_provider.dart';

final continueWatchingProvider =
    FutureProvider<List<ContinueWatchingItem>>((ref) async {
  final api = await ref.watch(progressApiProvider.future);
  final raw = await api.continueWatching();
  final items = (raw['items'] as List).cast<Map<String, dynamic>>();
  return items.map(ContinueWatchingItem.fromJson).toList();
});
```

> Confirm `ProgressApi.continueWatching()` exists (in `lib/data/remote/endpoints/progress_api.dart`). If not, add it: `Future<Map<String, dynamic>> continueWatching() => _client.getJson('/api/progress/continue-watching');`.

- [ ] **Step 3: Mocktail test (api returns 1 item, parse + return)**

- [ ] **Step 4: Codegen + run + commit**

```bash
dart run build_runner build --delete-conflicting-outputs
git add lib/domain/models/continue_watching_item.dart \
        lib/domain/models/continue_watching_item.freezed.dart \
        lib/domain/models/continue_watching_item.g.dart \
        lib/state/continue_watching_provider.dart \
        test/state/continue_watching_provider_test.dart
git commit -m "state: continueWatchingProvider — fetches /api/progress/continue-watching"
```

---

### Task 10: HomePage — prepend "Continua a guardare" row when items + plugin access

**Files:**
- Modify: `lib/presentation/pages/home_page.dart`

- [ ] **Step 1: Update HomePage to read both providers and prepend a row**

```dart
final access = ref.watch(pluginAccessProvider);
final continueWatching = access == PluginAccess.available
    ? ref.watch(continueWatchingProvider)
    : const AsyncValue<List<ContinueWatchingItem>>.data([]);

// In the data callback:
data: (rows) {
  final cwRow = continueWatching.maybeWhen(
    data: (items) => items.isNotEmpty
        ? MediaRow(
            title: 'Continua a guardare',
            items: items.map((i) => MediaSummary(
              tmdbId: i.tmdbId, mediaType: i.mediaType,
              title: i.title, year: i.year, posterUrl: i.posterUrl,
            )).toList(),
            onTap: (m) => context.go('/title/${m.tmdbId}?media_type=${m.mediaType}'),
          )
        : null,
    orElse: () => null,
  );
  return ListView(
    children: [
      if (cwRow != null) cwRow,
      ...rows.map((c) => MediaRow(
        title: c.title,
        items: c.items,
        onTap: (m) => context.go('/title/${m.tmdbId}?media_type=${m.mediaType}'),
      )),
    ],
  );
},
```

- [ ] **Step 2: Run + commit**

```bash
git add lib/presentation/pages/home_page.dart
git commit -m "pages: HomePage prepends Continua-a-guardare row when plugin access + items"
```

---

## Acceptance criteria

- ~225 tests pass (~18 new across this plan).
- `flutter analyze` clean.
- From a populated home with Breaking Bad seeded, tap title → tap S01E01 → `/watch/1396?media_type=tv&season=1&episode=1` → player loads (or shows clear error if no plugin can satisfy the title).
- Heart and bookmark icons toggle on the title page; backend `favorites` and `watchlist` tables update.
- After 30 seconds of playback, the backend's `watch_progress` row exists with the correct position.
- Closing the player and returning to home shows Breaking Bad in the "Continua a guardare" row.
- A user with no plugin access does NOT see "Continua a guardare" (gated correctly).

## Manual smoke (operator)

This needs the echo fixture's `getStreams` to return a real upstream HLS to actually verify playback. Two paths:

**Quick path** — temporarily edit `streamload-plugins/plugins/_fixture/echo.js` to make `getStreams` return Apple BipBop:
```js
export async function getStreams(_) {
  return {
    manifest_url: "https://devstreaming-cdn.apple.com/videos/streaming/examples/img_bipbop_adv_example_ts/master.m3u8",
    headers: {},
    is_drm: false,
  };
}
```
Bump `registry.json` sha256 + push. App refresh in 30 min OR `Settings → Plugin → Aggiorna`. Then any title's Watch button will play BipBop.

**Real path** — port one of the v2 plugins (e.g. streamingcommunity) to the JS sandbox shape. Out of scope for this plan; defer to "real plugin authoring" work.
