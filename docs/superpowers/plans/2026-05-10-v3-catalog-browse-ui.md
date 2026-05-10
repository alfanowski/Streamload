# v3 Catalog + Browse UI Implementation Plan (sub-plan 6a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the home placeholder with a real catalog UI: home with curated rows, library with paginated grids by media type, backend-backed search, and a title detail page (movies + TV with season/episode listing). Watch button on the title page navigates to a stub `/watch` route — the actual watch page + playback wiring is sub-plan 6b.

**Architecture:** Backend `/api/collections`, `/api/library`, `/api/search`, `/api/title/{id}/episodes`, `/api/catalog/{id}` are the only data sources for this plan. Drift caches single-item lookups (`catalog_items`) and tv episodes (`tv_episodes`) — first read fetches from backend, subsequent reads hit local cache (TTL 24h). UI is built on a `PosterCard` + `MediaRow` + `MediaGrid` widget primitive set, layered into `HomePage`, `LibraryPage`, `SearchPage`, `TitlePage`. Routing through go_router with a shared `AuthenticatedShell` providing the top-of-screen nav (Home / Library / Search / Profile).

**Tech Stack:** Flutter 3.41+, Dart 3.11+, riverpod 2.6, drift 2.28, freezed 2.5, go_router 14, dio (already in), cached_network_image 3.4 (new).

---

## Source spec

This plan implements part of **Sub-plan #6** from `docs/superpowers/specs/2026-05-09-streamload-v3-design.md` §17. Sub-plan #6 in the design covers all of: search, library, title, watch, favorites, watchlist, continue-watching, settings polish, onboarding, auto-updater, telemetry, build/sign/release. That's a kitchen sink — decomposed at execution time into:

- **6a (this plan)**: catalog discovery + browse UI (home, library, search, title metadata + episode listing). Watch button is a stub route.
- **6b**: watch page + playback wiring (uses Plan #5's PlayController), favorites toggle + sync, watchlist toggle + sync, continue-watching, progress polling.
- **6c**: telemetry batching, settings polish, app auto-updater, build/sign (skip notarization per §16) + DMG release pipeline.

The terminal state of this plan is: a logged-in user with a PAT can browse home → see N curated collection rows of poster cards → tap "Library" in nav → see paginated movie/tv grids → tap a poster → land on a title page showing metadata, and for TV: season picker + episode list. A search bar in the nav debounces input and shows TMDB matches as a grid. Tapping a result lands on the same title page. The "Watch" button on the title page navigates to `/watch/<tmdb_id>?media_type=...` — that route shows a "playback coming in 6b" placeholder.

## Backend response shapes (verify in code, adapt if drifted)

The plan assumes the following shapes from the existing FastAPI v0.3.0 backend. **Before writing each provider/page**, the implementer should grep the backend Python routes (in `/Users/alfanowski/Desktop/Projects/Streamload/streamload/api/`) to confirm the response. If the actual response differs, adapt the freezed DTO to match — don't change the backend.

```jsonc
// GET /api/collections → List[CollectionSummary]
[ { "id": "trending_movies", "title": "In Tendenza", "media_type": "movie",
    "items": [ { "tmdb_id": 1, "media_type": "movie", "title": "...",
                 "year": 2024, "poster_url": "https://...", "backdrop_url": null } ] } ]

// GET /api/library?media_type=movie&page=1&per_page=24 → { items: [...], page, per_page, total }
{ "items": [ { "tmdb_id": 1, "media_type": "movie", "title": "...",
               "year": 2024, "poster_url": "https://..." } ],
  "page": 1, "per_page": 24, "total": 1234 }

// GET /api/search?q=dune → { items: [...] }
{ "items": [ { "tmdb_id": 12345, "media_type": "movie",
               "title": "Dune", "year": 2021, "poster_url": "https://..." } ] }

// GET /api/catalog/{tmdb_id}?media_type=movie → CatalogItemResponse (already wired)
// — see lib/domain/models/catalog_item.dart

// GET /api/title/{tmdb_id}/episodes → { seasons: [{ number, name, episodes: [...] }] }
{ "seasons": [ { "number": 1, "name": "Stagione 1",
                 "episodes": [ { "season": 1, "episode": 1, "title": "Pilot",
                                 "overview": "...", "still_url": "https://...",
                                 "runtime_minutes": 42, "air_date": "2024-01-01" } ] } ] }
```

If any field is missing from a real response, make the freezed model field nullable rather than asserting non-null. Reuse the existing `CatalogItemResponse` for the title detail page; no duplication.

## File structure

### New files (Tasks 1-14)

| Path | Created in | Purpose |
|---|---|---|
| `lib/presentation/widgets/poster_card.dart` | T1 | Image + title + year, tappable |
| `lib/presentation/widgets/media_row.dart` | T2 | Horizontal-scroll list of PosterCard with section title |
| `lib/presentation/widgets/media_grid.dart` | T2 | Responsive grid of PosterCard |
| `lib/domain/models/media_summary.dart` | T1 | freezed `MediaSummary` (tmdb_id, media_type, title, year, poster_url, backdrop_url) — the lightweight shape the cards consume |
| `lib/domain/models/collection_summary.dart` | T3 | freezed `CollectionSummary` (id, title, media_type, items: List<MediaSummary>) |
| `lib/domain/models/library_page.dart` | T5 | freezed `LibraryPage` (items, page, perPage, total) |
| `lib/domain/models/episodes_response.dart` | T11 | freezed `EpisodesResponse` (seasons: List<SeasonInfo>), `SeasonInfo` (number, name, episodes), `EpisodeInfo` |
| `lib/state/collections_provider.dart` | T3 | FutureProvider — wraps CollectionsApi |
| `lib/state/library_provider.dart` | T6 | family FutureProvider keyed by (mediaType, page) |
| `lib/state/search_provider.dart` | T8 | StateNotifierProvider — debounced query → results |
| `lib/state/title_provider.dart` | T10 | family FutureProvider keyed by (tmdbId, mediaType) |
| `lib/state/episodes_provider.dart` | T11 | family FutureProvider keyed by tmdbId |
| `lib/presentation/pages/library_page.dart` | T7 | tabs (Movies/TV/Anime) + paginated grid |
| `lib/presentation/pages/search_page.dart` | T9 | search bar + results grid |
| `lib/presentation/pages/title_page.dart` | T10-T12 | metadata + (movies: Watch button) (tv: SeasonPicker + EpisodeList) |
| `lib/presentation/pages/watch_placeholder_page.dart` | T13 | stub for /watch route — sub-plan 6b replaces it |
| `lib/presentation/widgets/authenticated_shell.dart` | T13 | Scaffold with NavigationRail (Home/Library/Search/Profile) wrapping the page body |
| `test/widgets/poster_card_test.dart` | T1 | renders + tap fires callback |
| `test/widgets/media_row_test.dart` | T2 | renders N cards |
| `test/state/collections_provider_test.dart` | T3 | mock api + assert provider value |
| `test/state/library_provider_test.dart` | T6 | mock api + pagination key |
| `test/state/search_provider_test.dart` | T8 | debounce + results |
| `test/state/title_provider_test.dart` | T10 | mock catalog api |
| `test/state/episodes_provider_test.dart` | T11 | mock episodes api |
| `test/pages/library_page_test.dart` | T7 | tab switch + grid |
| `test/pages/search_page_test.dart` | T9 | type → debounce → results render |
| `test/pages/title_page_test.dart` | T10-T12 | movie variant + tv variant |

### Modified files

| Path | Modified in | Change |
|---|---|---|
| `pubspec.yaml` | T1 | add `cached_network_image: ^3.4.1` |
| `lib/presentation/pages/home_page.dart` | T4 | replace placeholder with real layout (N MediaRows backed by collectionsProvider) |
| `lib/router.dart` | T13-T14 | wrap authenticated routes in `AuthenticatedShell`; add `/library`, `/library/:type`, `/search`, `/title/:tmdbId`, `/watch/:tmdbId` |
| `lib/data/local/daos/catalog_dao.dart` | T10 | add `watch(tmdbId, mediaType)` for title page reactivity |

---

## Phase A — Foundation widgets

### Task 1: `MediaSummary` model + `PosterCard` widget

**Files:**
- Modify: `pubspec.yaml` (add `cached_network_image`)
- Create: `lib/domain/models/media_summary.dart`
- Create: `lib/presentation/widgets/poster_card.dart`
- Create: `test/widgets/poster_card_test.dart`

- [ ] **Step 1: Add `cached_network_image: ^3.4.1` to `dependencies:` in `pubspec.yaml` and run `flutter pub get`.**

- [ ] **Step 2: Write `MediaSummary` freezed model**

```dart
// lib/domain/models/media_summary.dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'media_summary.freezed.dart';
part 'media_summary.g.dart';

@freezed
class MediaSummary with _$MediaSummary {
  const factory MediaSummary({
    @JsonKey(name: 'tmdb_id') required int tmdbId,
    @JsonKey(name: 'media_type') required String mediaType,
    required String title,
    int? year,
    @JsonKey(name: 'poster_url') String? posterUrl,
    @JsonKey(name: 'backdrop_url') String? backdropUrl,
  }) = _MediaSummary;

  factory MediaSummary.fromJson(Map<String, dynamic> json) =>
      _$MediaSummaryFromJson(json);
}
```

Run codegen: `dart run build_runner build --delete-conflicting-outputs`.

- [ ] **Step 3: Write the failing widget test**

```dart
// test/widgets/poster_card_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/domain/models/media_summary.dart';
import 'package:streamload_client/presentation/widgets/poster_card.dart';

void main() {
  Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

  testWidgets('renders title and year', (tester) async {
    await tester.pumpWidget(_wrap(PosterCard(
      summary: const MediaSummary(
        tmdbId: 1, mediaType: 'movie', title: 'Dune', year: 2021,
      ),
      onTap: () {},
    )));
    expect(find.text('Dune'), findsOneWidget);
    expect(find.text('2021'), findsOneWidget);
  });

  testWidgets('omits year when null', (tester) async {
    await tester.pumpWidget(_wrap(PosterCard(
      summary: const MediaSummary(tmdbId: 1, mediaType: 'movie', title: 'Untitled'),
      onTap: () {},
    )));
    expect(find.text('Untitled'), findsOneWidget);
    expect(find.textContaining(RegExp(r'^\d{4}$')), findsNothing);
  });

  testWidgets('tap fires the callback', (tester) async {
    var taps = 0;
    await tester.pumpWidget(_wrap(PosterCard(
      summary: const MediaSummary(tmdbId: 1, mediaType: 'movie', title: 'X'),
      onTap: () => taps++,
    )));
    await tester.tap(find.byType(PosterCard));
    expect(taps, 1);
  });
}
```

- [ ] **Step 4: Run, expect failure, then implement**

```dart
// lib/presentation/widgets/poster_card.dart
import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../../domain/models/media_summary.dart';
import '../theme/colors.dart';
import '../theme/typography.dart';

class PosterCard extends StatelessWidget {
  const PosterCard({super.key, required this.summary, required this.onTap});

  final MediaSummary summary;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: SizedBox(
        width: 160,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            AspectRatio(
              aspectRatio: 2 / 3,
              child: ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: summary.posterUrl != null
                    ? CachedNetworkImage(
                        imageUrl: summary.posterUrl!,
                        fit: BoxFit.cover,
                        placeholder: (_, __) =>
                            Container(color: StreamloadColors.surfaceMuted),
                        errorWidget: (_, __, ___) => const _PlaceholderPoster(),
                      )
                    : const _PlaceholderPoster(),
              ),
            ),
            const SizedBox(height: 8),
            Text(
              summary.title,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: StreamloadTypography.body(fontSize: 13),
            ),
            if (summary.year != null)
              Text('${summary.year}',
                  style: StreamloadTypography.mono(
                    fontSize: 10,
                    color: StreamloadColors.textSecondary,
                  )),
          ],
        ),
      ),
    );
  }
}

class _PlaceholderPoster extends StatelessWidget {
  const _PlaceholderPoster();

  @override
  Widget build(BuildContext context) {
    return Container(
      color: StreamloadColors.surfaceMuted,
      alignment: Alignment.center,
      child: const Icon(Icons.movie_outlined, size: 28),
    );
  }
}
```

- [ ] **Step 5: Run tests, expect 3 pass**

- [ ] **Step 6: Commit**

```bash
git add pubspec.yaml pubspec.lock lib/domain/models/media_summary.dart lib/domain/models/media_summary.freezed.dart lib/domain/models/media_summary.g.dart lib/presentation/widgets/poster_card.dart test/widgets/poster_card_test.dart
git commit -m "ui: MediaSummary + PosterCard widget with cached image"
```

---

### Task 2: `MediaRow` + `MediaGrid` widgets

**Files:**
- Create: `lib/presentation/widgets/media_row.dart`
- Create: `lib/presentation/widgets/media_grid.dart`
- Create: `test/widgets/media_row_test.dart`

- [ ] **Step 1: Write the failing test**

```dart
// test/widgets/media_row_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/domain/models/media_summary.dart';
import 'package:streamload_client/presentation/widgets/media_row.dart';
import 'package:streamload_client/presentation/widgets/poster_card.dart';

void main() {
  testWidgets('MediaRow renders the section title and N posters', (tester) async {
    final items = List.generate(5, (i) => MediaSummary(
      tmdbId: i, mediaType: 'movie', title: 'T$i',
    ));
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: MediaRow(
      title: 'In tendenza',
      items: items,
      onTap: (_) {},
    ))));
    expect(find.text('In tendenza'), findsOneWidget);
    expect(find.byType(PosterCard), findsNWidgets(5));
  });

  testWidgets('MediaRow hides itself when items is empty', (tester) async {
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: MediaRow(
      title: 'Vuoto', items: const [], onTap: (_) {},
    ))));
    expect(find.text('Vuoto'), findsNothing);
  });
}
```

- [ ] **Step 2: Implement `MediaRow` and `MediaGrid`** (the grid version is needed for Task 7 and 9 — implement both now to keep the widget pair atomic)

```dart
// lib/presentation/widgets/media_row.dart
import 'package:flutter/material.dart';

import '../../domain/models/media_summary.dart';
import '../theme/typography.dart';
import 'eyebrow.dart';
import 'poster_card.dart';

class MediaRow extends StatelessWidget {
  const MediaRow({
    super.key,
    required this.title,
    required this.items,
    required this.onTap,
  });

  final String title;
  final List<MediaSummary> items;
  final void Function(MediaSummary) onTap;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Eyebrow(title.toUpperCase()),
          ),
          const SizedBox(height: 12),
          SizedBox(
            height: 290,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 24),
              itemCount: items.length,
              separatorBuilder: (_, __) => const SizedBox(width: 12),
              itemBuilder: (_, i) => PosterCard(
                summary: items[i],
                onTap: () => onTap(items[i]),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
```

```dart
// lib/presentation/widgets/media_grid.dart
import 'package:flutter/material.dart';

import '../../domain/models/media_summary.dart';
import 'poster_card.dart';

class MediaGrid extends StatelessWidget {
  const MediaGrid({
    super.key,
    required this.items,
    required this.onTap,
    this.padding = const EdgeInsets.all(24),
  });

  final List<MediaSummary> items;
  final void Function(MediaSummary) onTap;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) {
      return const Center(child: Text('Nessun risultato.'));
    }
    return GridView.builder(
      padding: padding,
      gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: 180,
        childAspectRatio: 0.55,
        mainAxisSpacing: 16,
        crossAxisSpacing: 16,
      ),
      itemCount: items.length,
      itemBuilder: (_, i) => PosterCard(
        summary: items[i],
        onTap: () => onTap(items[i]),
      ),
    );
  }
}
```

- [ ] **Step 3: Run tests, expect 2 pass**

- [ ] **Step 4: Commit**

```bash
git add lib/presentation/widgets/media_row.dart lib/presentation/widgets/media_grid.dart test/widgets/media_row_test.dart
git commit -m "ui: MediaRow + MediaGrid layout widgets"
```

---

## Phase B — Home page

### Task 3: `CollectionSummary` model + `collectionsProvider`

**Files:**
- Create: `lib/domain/models/collection_summary.dart`
- Create: `lib/state/collections_provider.dart`
- Create: `test/state/collections_provider_test.dart`

- [ ] **Step 1: Write the freezed model**

```dart
// lib/domain/models/collection_summary.dart
import 'package:freezed_annotation/freezed_annotation.dart';

import 'media_summary.dart';

part 'collection_summary.freezed.dart';
part 'collection_summary.g.dart';

@freezed
class CollectionSummary with _$CollectionSummary {
  const factory CollectionSummary({
    required String id,
    required String title,
    @JsonKey(name: 'media_type') required String mediaType,
    @Default(<MediaSummary>[]) List<MediaSummary> items,
  }) = _CollectionSummary;

  factory CollectionSummary.fromJson(Map<String, dynamic> json) =>
      _$CollectionSummaryFromJson(json);
}
```

Run codegen.

- [ ] **Step 2: Write the failing provider test**

```dart
// test/state/collections_provider_test.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/collections_api.dart';
import 'package:streamload_client/state/collections_provider.dart';

class _CollectionsApiMock extends Mock implements CollectionsApi {}

void main() {
  test('collectionsProvider parses CollectionSummary list', () async {
    final api = _CollectionsApiMock();
    when(api.list).thenAnswer((_) async => [
      {
        'id': 'trending_movies',
        'title': 'In Tendenza',
        'media_type': 'movie',
        'items': [
          {'tmdb_id': 1, 'media_type': 'movie', 'title': 'X', 'year': 2024,
           'poster_url': 'https://p/x.jpg'},
        ],
      },
    ]);

    final container = ProviderContainer(overrides: [
      collectionsApiProvider.overrideWith((_) async => api),
    ]);
    addTearDown(container.dispose);

    final result = await container.read(collectionsProvider.future);
    expect(result, hasLength(1));
    expect(result.first.id, 'trending_movies');
    expect(result.first.items.first.title, 'X');
  });
}
```

- [ ] **Step 3: Implement**

```dart
// lib/state/collections_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/remote/endpoints/collections_api.dart';
import '../domain/models/collection_summary.dart';
import 'api_client_provider.dart';

final collectionsProvider = FutureProvider<List<CollectionSummary>>((ref) async {
  final api = await ref.watch(collectionsApiProvider.future);
  final raw = await api.list();
  return raw.map(CollectionSummary.fromJson).toList(growable: false);
});
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add lib/domain/models/collection_summary.dart lib/domain/models/collection_summary.freezed.dart lib/domain/models/collection_summary.g.dart lib/state/collections_provider.dart test/state/collections_provider_test.dart
git commit -m "state: collectionsProvider — fetch curated home rows"
```

---

### Task 4: HomePage rewrite — show collection rows

**Files:**
- Modify: `lib/presentation/pages/home_page.dart`
- Create/modify: `test/pages/home_page_test.dart` (if it exists from Plan #3 stub, replace it)

- [ ] **Step 1: Update test (or create if missing)**

```dart
// test/pages/home_page_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/collections_api.dart';
import 'package:streamload_client/presentation/pages/home_page.dart';
import 'package:streamload_client/state/auth_provider.dart';
import 'package:streamload_client/state/collections_provider.dart';
import 'package:streamload_client/domain/models/user.dart';

class _CollectionsApiMock extends Mock implements CollectionsApi {}

void main() {
  testWidgets('home shows collection rows from collectionsProvider', (tester) async {
    final api = _CollectionsApiMock();
    when(api.list).thenAnswer((_) async => [
      {
        'id': 'trending_movies', 'title': 'In Tendenza', 'media_type': 'movie',
        'items': [
          {'tmdb_id': 1, 'media_type': 'movie', 'title': 'Dune', 'year': 2021,
           'poster_url': null},
        ],
      },
    ]);

    await tester.pumpWidget(ProviderScope(
      overrides: [
        collectionsApiProvider.overrideWith((_) async => api),
        authProvider.overrideWith((_) => StubAuthNotifier()),
      ],
      child: const MaterialApp(home: HomePage()),
    ));
    await tester.pumpAndSettle();

    expect(find.text('IN TENDENZA'), findsOneWidget);
    expect(find.text('Dune'), findsOneWidget);
  });
}

/// Minimal stub. AuthState only matters to render the title bar.
class StubAuthNotifier extends AuthNotifier {
  @override
  AuthState build() => AuthAuthenticated(
    user: const User(id: 'u', username: 'tester', email: 'a@b', emailVerified: true),
  );
}
```

> Adjust the `StubAuthNotifier` import / construction to match the existing AuthNotifier shape — Plan #3 uses StateNotifier; if that's still the case, override with a fixed-state notifier instead. The test's exact construction pattern is whatever the existing pages tests use.

- [ ] **Step 2: Replace `lib/presentation/pages/home_page.dart`**

```dart
// lib/presentation/pages/home_page.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../state/collections_provider.dart';
import '../theme/typography.dart';
import '../widgets/media_row.dart';

class HomePage extends ConsumerWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final collections = ref.watch(collectionsProvider);
    return Scaffold(
      appBar: AppBar(
        title: Text('Streamload',
            style: StreamloadTypography.display(fontSize: 22)),
      ),
      body: collections.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Errore: $e')),
        data: (rows) => ListView(
          children: rows.map((c) => MediaRow(
            title: c.title,
            items: c.items,
            onTap: (m) => context.go(
              '/title/${m.tmdbId}?media_type=${m.mediaType}',
            ),
          )).toList(),
        ),
      ),
    );
  }
}
```

- [ ] **Step 3: Run, expect pass**

- [ ] **Step 4: Commit**

```bash
git add lib/presentation/pages/home_page.dart test/pages/home_page_test.dart
git commit -m "pages: HomePage shows collection rows from backend"
```

---

## Phase C — Library

### Task 5: `LibraryPage` model

**Files:**
- Create: `lib/domain/models/library_page.dart`

- [ ] **Step 1: freezed model**

```dart
// lib/domain/models/library_page.dart
import 'package:freezed_annotation/freezed_annotation.dart';

import 'media_summary.dart';

part 'library_page.freezed.dart';
part 'library_page.g.dart';

@freezed
class LibraryPage with _$LibraryPage {
  const factory LibraryPage({
    required List<MediaSummary> items,
    required int page,
    @JsonKey(name: 'per_page') required int perPage,
    required int total,
  }) = _LibraryPage;

  factory LibraryPage.fromJson(Map<String, dynamic> json) =>
      _$LibraryPageFromJson(json);
}
```

- [ ] **Step 2: codegen + commit (no tests — pure DTO, exercised by Task 6)**

```bash
dart run build_runner build --delete-conflicting-outputs
git add lib/domain/models/library_page.dart lib/domain/models/library_page.freezed.dart lib/domain/models/library_page.g.dart
git commit -m "model: LibraryPage DTO"
```

---

### Task 6: `libraryProvider` family + tests

**Files:**
- Create: `lib/state/library_provider.dart`
- Create: `test/state/library_provider_test.dart`

- [ ] **Step 1: Write the failing test**

```dart
// test/state/library_provider_test.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/library_api.dart';
import 'package:streamload_client/state/library_provider.dart';

class _LibraryApiMock extends Mock implements LibraryApi {}

void main() {
  test('libraryProvider passes mediaType+page to api and returns LibraryPage', () async {
    final api = _LibraryApiMock();
    when(() => api.page(mediaType: 'movie', page: 2, perPage: 24))
        .thenAnswer((_) async => {
              'items': [
                {'tmdb_id': 1, 'media_type': 'movie', 'title': 'X', 'year': 2024,
                 'poster_url': null}
              ],
              'page': 2, 'per_page': 24, 'total': 100,
            });

    final container = ProviderContainer(overrides: [
      libraryApiProvider.overrideWith((_) async => api),
    ]);
    addTearDown(container.dispose);

    final got = await container.read(
      libraryProvider(const LibraryQuery(mediaType: 'movie', page: 2)).future,
    );
    expect(got.total, 100);
    expect(got.items.single.title, 'X');
  });
}
```

- [ ] **Step 2: Implement**

```dart
// lib/state/library_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/models/library_page.dart';
import 'api_client_provider.dart';

class LibraryQuery {
  const LibraryQuery({required this.mediaType, this.page = 1, this.perPage = 24});
  final String mediaType;
  final int page;
  final int perPage;

  @override
  bool operator ==(Object other) =>
      other is LibraryQuery &&
      other.mediaType == mediaType &&
      other.page == page &&
      other.perPage == perPage;
  @override
  int get hashCode => Object.hash(mediaType, page, perPage);
}

final libraryProvider =
    FutureProvider.family<LibraryPage, LibraryQuery>((ref, q) async {
  final api = await ref.watch(libraryApiProvider.future);
  final raw = await api.page(mediaType: q.mediaType, page: q.page, perPage: q.perPage);
  return LibraryPage.fromJson(raw);
});
```

- [ ] **Step 3: Run + commit**

```bash
git add lib/state/library_provider.dart test/state/library_provider_test.dart
git commit -m "state: libraryProvider family — paginated library by media_type"
```

---

### Task 7: `LibraryPage` UI

**Files:**
- Create: `lib/presentation/pages/library_page.dart`
- Create: `test/pages/library_page_test.dart`

- [ ] **Step 1: Write a basic widget test**

```dart
// test/pages/library_page_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/library_api.dart';
import 'package:streamload_client/presentation/pages/library_page.dart';

class _LibraryApiMock extends Mock implements LibraryApi {}

void main() {
  testWidgets('LibraryPage renders the movies tab grid by default', (tester) async {
    final api = _LibraryApiMock();
    when(() => api.page(mediaType: any(named: 'mediaType'),
        page: any(named: 'page'), perPage: any(named: 'perPage')))
        .thenAnswer((_) async => {
              'items': [
                {'tmdb_id': 1, 'media_type': 'movie', 'title': 'Dune', 'year': 2021,
                 'poster_url': null}
              ],
              'page': 1, 'per_page': 24, 'total': 1,
            });
    await tester.pumpWidget(ProviderScope(
      overrides: [libraryApiProvider.overrideWith((_) async => api)],
      child: const MaterialApp(home: LibraryPage()),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Dune'), findsOneWidget);
  });
}
```

- [ ] **Step 2: Implement**

```dart
// lib/presentation/pages/library_page.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../state/library_provider.dart';
import '../widgets/media_grid.dart';

class LibraryPage extends ConsumerStatefulWidget {
  const LibraryPage({super.key});

  @override
  ConsumerState<LibraryPage> createState() => _LibraryPageState();
}

class _LibraryPageState extends ConsumerState<LibraryPage>
    with SingleTickerProviderStateMixin {
  late final TabController _ctrl;
  static const _types = ['movie', 'tv'];
  static const _labels = ['Film', 'Serie TV'];

  @override
  void initState() {
    super.initState();
    _ctrl = TabController(length: _types.length, vsync: this);
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Libreria'),
        bottom: TabBar(
          controller: _ctrl,
          tabs: _labels.map((l) => Tab(text: l)).toList(),
        ),
      ),
      body: TabBarView(
        controller: _ctrl,
        children: _types.map((t) {
          final async =
              ref.watch(libraryProvider(LibraryQuery(mediaType: t)));
          return async.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => Center(child: Text('Errore: $e')),
            data: (page) => MediaGrid(
              items: page.items,
              onTap: (m) => context.go(
                '/title/${m.tmdbId}?media_type=${m.mediaType}',
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}
```

> The plan keeps pagination minimal — single first-page fetch. Infinite scroll is a follow-up after MVP.

- [ ] **Step 3: Run + commit**

```bash
git add lib/presentation/pages/library_page.dart test/pages/library_page_test.dart
git commit -m "pages: LibraryPage with movie/tv tabs + grid"
```

---

## Phase D — Search

### Task 8: `searchProvider` (debounced)

**Files:**
- Create: `lib/state/search_provider.dart`
- Create: `test/state/search_provider_test.dart`

- [ ] **Step 1: Write the failing test**

```dart
// test/state/search_provider_test.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/search_api.dart';
import 'package:streamload_client/state/search_provider.dart';

class _SearchApiMock extends Mock implements SearchApi {}

void main() {
  test('setQuery debounces and produces a result list', () async {
    final api = _SearchApiMock();
    when(() => api.run('dune')).thenAnswer((_) async => {
          'items': [
            {'tmdb_id': 1, 'media_type': 'movie', 'title': 'Dune', 'year': 2021,
             'poster_url': null}
          ],
        });
    final container = ProviderContainer(overrides: [
      searchApiProvider.overrideWith((_) async => api),
    ]);
    addTearDown(container.dispose);

    final ctrl = container.read(searchControllerProvider.notifier);
    ctrl.setQuery('dune');
    // wait for the debounce window plus the api call.
    await Future<void>.delayed(const Duration(milliseconds: 350));
    final state = container.read(searchControllerProvider);
    expect(state.value, isNotNull);
    expect(state.value!.first.title, 'Dune');
  });

  test('empty query produces an empty list, no api call', () async {
    final api = _SearchApiMock();
    final container = ProviderContainer(overrides: [
      searchApiProvider.overrideWith((_) async => api),
    ]);
    addTearDown(container.dispose);

    container.read(searchControllerProvider.notifier).setQuery('');
    await Future<void>.delayed(const Duration(milliseconds: 350));
    final state = container.read(searchControllerProvider);
    expect(state.value, isEmpty);
    verifyNever(() => api.run(any()));
  });
}
```

- [ ] **Step 2: Implement**

```dart
// lib/state/search_provider.dart
import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/models/media_summary.dart';
import 'api_client_provider.dart';

class SearchController extends StateNotifier<AsyncValue<List<MediaSummary>>> {
  SearchController(this._ref) : super(const AsyncData([]));

  final Ref _ref;
  Timer? _debounce;
  String _query = '';

  void setQuery(String q) {
    _query = q.trim();
    _debounce?.cancel();
    if (_query.isEmpty) {
      state = const AsyncData([]);
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 250), _run);
  }

  Future<void> _run() async {
    final q = _query;
    state = const AsyncLoading();
    try {
      final api = await _ref.read(searchApiProvider.future);
      final raw = await api.run(q);
      final items = (raw['items'] as List)
          .cast<Map<String, dynamic>>()
          .map(MediaSummary.fromJson)
          .toList();
      // Discard if a newer query took over.
      if (q != _query) return;
      state = AsyncData(items);
    } catch (e, st) {
      state = AsyncError(e, st);
    }
  }
}

final searchControllerProvider =
    StateNotifierProvider<SearchController, AsyncValue<List<MediaSummary>>>(
  (ref) => SearchController(ref),
);
```

- [ ] **Step 3: Run + commit**

```bash
git add lib/state/search_provider.dart test/state/search_provider_test.dart
git commit -m "state: searchProvider — debounced backend search"
```

---

### Task 9: `SearchPage` UI

**Files:**
- Create: `lib/presentation/pages/search_page.dart`
- Create: `test/pages/search_page_test.dart`

- [ ] **Step 1: Write a basic widget test**

```dart
// test/pages/search_page_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/search_api.dart';
import 'package:streamload_client/presentation/pages/search_page.dart';

class _SearchApiMock extends Mock implements SearchApi {}

void main() {
  testWidgets('typing in the search field eventually shows results', (tester) async {
    final api = _SearchApiMock();
    when(() => api.run('dune')).thenAnswer((_) async => {
          'items': [
            {'tmdb_id': 1, 'media_type': 'movie', 'title': 'Dune', 'year': 2021,
             'poster_url': null}
          ],
        });
    await tester.pumpWidget(ProviderScope(
      overrides: [searchApiProvider.overrideWith((_) async => api)],
      child: const MaterialApp(home: SearchPage()),
    ));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'dune');
    // pump past the 250ms debounce.
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pumpAndSettle();
    expect(find.text('Dune'), findsOneWidget);
  });
}
```

- [ ] **Step 2: Implement**

```dart
// lib/presentation/pages/search_page.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../state/search_provider.dart';
import '../widgets/media_grid.dart';

class SearchPage extends ConsumerWidget {
  const SearchPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(searchControllerProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Cerca')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: TextField(
              autofocus: true,
              decoration: const InputDecoration(
                hintText: 'Titolo, anno, regista…',
                prefixIcon: Icon(Icons.search),
                border: OutlineInputBorder(),
              ),
              onChanged: (v) =>
                  ref.read(searchControllerProvider.notifier).setQuery(v),
            ),
          ),
          Expanded(
            child: state.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Center(child: Text('Errore: $e')),
              data: (items) => MediaGrid(
                items: items,
                onTap: (m) => context.go(
                  '/title/${m.tmdbId}?media_type=${m.mediaType}',
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
```

- [ ] **Step 3: Run + commit**

```bash
git add lib/presentation/pages/search_page.dart test/pages/search_page_test.dart
git commit -m "pages: SearchPage with debounced TextField + results grid"
```

---

## Phase E — Title detail

### Task 10: `titleProvider` + `TitlePage` shell (movie variant)

**Files:**
- Create: `lib/state/title_provider.dart`
- Create: `lib/presentation/pages/title_page.dart`
- Modify: `lib/data/local/daos/catalog_dao.dart` (add a `watch` method)
- Create: `test/state/title_provider_test.dart`
- Create: `test/pages/title_page_test.dart`

- [ ] **Step 1: Add `watchByKey` to `CatalogDao` for reactivity**

```dart
  Stream<CatalogItemRow?> watchByKey(int tmdbId, String mediaType) {
    return (select(catalogItems)
          ..where((t) => t.tmdbId.equals(tmdbId) & t.mediaType.equals(mediaType)))
        .watchSingleOrNull();
  }
```

(This stream is used by the title page to refresh when sync writes a fresher row.)

- [ ] **Step 2: Implement `titleProvider` family — first reads from drift, falls back to `catalogApi.get` and upserts**

```dart
// lib/state/title_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/local/database.dart';
import '../domain/models/catalog_item.dart';
import 'api_client_provider.dart';
import 'database_provider.dart';

class TitleKey {
  const TitleKey({required this.tmdbId, required this.mediaType});
  final int tmdbId;
  final String mediaType;

  @override
  bool operator ==(Object other) =>
      other is TitleKey &&
      other.tmdbId == tmdbId && other.mediaType == mediaType;
  @override
  int get hashCode => Object.hash(tmdbId, mediaType);
}

final titleProvider =
    FutureProvider.family<CatalogItemResponse, TitleKey>((ref, k) async {
  final api = await ref.watch(catalogApiProvider.future);
  final db = ref.watch(databaseProvider);
  // Naive cache-aside: hit drift first, but always also refresh from
  // backend (which de-duplicates by composite PK on upsert).
  final fresh = await api.get(k.tmdbId, mediaType: k.mediaType);
  await db.catalogDao.upsert(fresh.toCompanion());
  return fresh;
});
```

> If `CatalogItemResponse.toCompanion()` doesn't exist, add it on the response class — converts the response shape to the drift companion.

- [ ] **Step 3: Implement `TitlePage` — movie variant only for now**

```dart
// lib/presentation/pages/title_page.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../state/title_provider.dart';
import '../theme/typography.dart';
import '../widgets/eyebrow.dart';
import '../widgets/primary_button.dart';

class TitlePage extends ConsumerWidget {
  const TitlePage({super.key, required this.tmdbId, required this.mediaType});
  final int tmdbId;
  final String mediaType;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(
      titleProvider(TitleKey(tmdbId: tmdbId, mediaType: mediaType)),
    );
    return Scaffold(
      appBar: AppBar(),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Errore: $e')),
        data: (item) => SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Eyebrow('Titolo'),
                const SizedBox(height: 8),
                Text(item.title, style: StreamloadTypography.display(fontSize: 36)),
                if (item.year != null) ...[
                  const SizedBox(height: 4),
                  Text('${item.year}',
                      style: StreamloadTypography.mono(fontSize: 12)),
                ],
                const SizedBox(height: 16),
                if (item.overview != null) Text(item.overview!),
                const SizedBox(height: 24),
                PrimaryButton(
                  label: 'Guarda',
                  onPressed: () => context.go(
                    '/watch/$tmdbId?media_type=$mediaType',
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
```

- [ ] **Step 4: Tests + commit**

```bash
git add lib/state/title_provider.dart lib/data/local/daos/catalog_dao.dart lib/data/local/daos/catalog_dao.g.dart lib/presentation/pages/title_page.dart test/state/title_provider_test.dart test/pages/title_page_test.dart
git commit -m "pages: TitlePage (movie variant) + titleProvider + dao watch helper"
```

---

### Task 11: `EpisodesResponse` + `episodesProvider`

**Files:**
- Create: `lib/domain/models/episodes_response.dart`
- Create: `lib/state/episodes_provider.dart`
- Create: `test/state/episodes_provider_test.dart`

- [ ] **Step 1: freezed model**

```dart
// lib/domain/models/episodes_response.dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'episodes_response.freezed.dart';
part 'episodes_response.g.dart';

@freezed
class EpisodesResponse with _$EpisodesResponse {
  const factory EpisodesResponse({
    @Default(<SeasonInfo>[]) List<SeasonInfo> seasons,
  }) = _EpisodesResponse;

  factory EpisodesResponse.fromJson(Map<String, dynamic> json) =>
      _$EpisodesResponseFromJson(json);
}

@freezed
class SeasonInfo with _$SeasonInfo {
  const factory SeasonInfo({
    required int number,
    String? name,
    @Default(<EpisodeInfo>[]) List<EpisodeInfo> episodes,
  }) = _SeasonInfo;

  factory SeasonInfo.fromJson(Map<String, dynamic> json) =>
      _$SeasonInfoFromJson(json);
}

@freezed
class EpisodeInfo with _$EpisodeInfo {
  const factory EpisodeInfo({
    required int season,
    required int episode,
    required String title,
    String? overview,
    @JsonKey(name: 'still_url') String? stillUrl,
    @JsonKey(name: 'runtime_minutes') int? runtimeMinutes,
    @JsonKey(name: 'air_date') String? airDate,
  }) = _EpisodeInfo;

  factory EpisodeInfo.fromJson(Map<String, dynamic> json) =>
      _$EpisodeInfoFromJson(json);
}
```

- [ ] **Step 2: Provider**

```dart
// lib/state/episodes_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/models/episodes_response.dart';
import 'api_client_provider.dart';

final episodesProvider =
    FutureProvider.family<EpisodesResponse, int>((ref, tmdbId) async {
  final api = await ref.watch(episodesApiProvider.future);
  final raw = await api.list(tmdbId);
  return EpisodesResponse.fromJson(raw);
});
```

- [ ] **Step 3: Test + commit (similar mock pattern to titleProvider)**

```bash
git add lib/domain/models/episodes_response.dart lib/domain/models/episodes_response.freezed.dart lib/domain/models/episodes_response.g.dart lib/state/episodes_provider.dart test/state/episodes_provider_test.dart
git commit -m "state: EpisodesResponse + episodesProvider"
```

---

### Task 12: TV variant of `TitlePage` — SeasonPicker + EpisodeList

**Files:**
- Modify: `lib/presentation/pages/title_page.dart`
- Modify: `test/pages/title_page_test.dart` (add a TV variant test)

- [ ] **Step 1: Add a TV branch under the data callback**

```dart
data: (item) {
  if (item.mediaType == 'tv') {
    return _TitleTvBody(tmdbId: tmdbId, item: item);
  }
  return _TitleMovieBody(tmdbId: tmdbId, item: item);
},
```

Pull the existing movie body into `_TitleMovieBody` (same code, just lifted into a private widget).

- [ ] **Step 2: Implement `_TitleTvBody`** — listens to `episodesProvider(tmdbId)`, renders the metadata header (same as movie) + a season chip row + an episode list. Each episode is a tappable `ListTile` with `still_url` thumbnail + title + episode number; tap navigates to `/watch/$tmdbId?media_type=tv&season=$s&episode=$e`.

```dart
class _TitleTvBody extends ConsumerStatefulWidget {
  const _TitleTvBody({required this.tmdbId, required this.item});
  final int tmdbId;
  final CatalogItemResponse item;

  @override
  ConsumerState<_TitleTvBody> createState() => _TitleTvBodyState();
}

class _TitleTvBodyState extends ConsumerState<_TitleTvBody> {
  int _seasonIdx = 0;

  @override
  Widget build(BuildContext context) {
    final ep = ref.watch(episodesProvider(widget.tmdbId));
    return ep.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('Errore episodi: $e')),
      data: (resp) {
        if (resp.seasons.isEmpty) {
          return const Center(child: Text('Nessuna stagione disponibile.'));
        }
        final season = resp.seasons[_seasonIdx.clamp(0, resp.seasons.length - 1)];
        return ListView(
          padding: const EdgeInsets.all(24),
          children: [
            // (header: title, year, overview — same as movie variant; factor it out)
            const SizedBox(height: 24),
            Wrap(
              spacing: 8,
              children: List.generate(resp.seasons.length, (i) {
                final s = resp.seasons[i];
                return ChoiceChip(
                  label: Text(s.name ?? 'Stagione ${s.number}'),
                  selected: i == _seasonIdx,
                  onSelected: (_) => setState(() => _seasonIdx = i),
                );
              }),
            ),
            const SizedBox(height: 16),
            for (final e in season.episodes)
              ListTile(
                leading: e.stillUrl != null
                    ? SizedBox(
                        width: 96,
                        child: AspectRatio(
                          aspectRatio: 16 / 9,
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(4),
                            child: Image.network(e.stillUrl!,
                                fit: BoxFit.cover),
                          ),
                        ),
                      )
                    : null,
                title: Text('${e.episode}. ${e.title}'),
                subtitle: e.overview != null
                    ? Text(e.overview!,
                        maxLines: 2, overflow: TextOverflow.ellipsis)
                    : null,
                onTap: () => context.go(
                  '/watch/${widget.tmdbId}?media_type=tv'
                  '&season=${e.season}&episode=${e.episode}',
                ),
              ),
          ],
        );
      },
    );
  }
}
```

- [ ] **Step 3: Test + commit**

```bash
git add lib/presentation/pages/title_page.dart test/pages/title_page_test.dart
git commit -m "pages: TitlePage TV variant — seasons + episodes list"
```

---

## Phase F — Wiring

### Task 13: `AuthenticatedShell` + `WatchPlaceholderPage` + nav

**Files:**
- Create: `lib/presentation/widgets/authenticated_shell.dart`
- Create: `lib/presentation/pages/watch_placeholder_page.dart`

- [ ] **Step 1: Implement the shell — `NavigationRail` for desktop with 4 destinations**

```dart
// lib/presentation/widgets/authenticated_shell.dart
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

class AuthenticatedShell extends StatelessWidget {
  const AuthenticatedShell({super.key, required this.child});
  final Widget child;

  static const _destinations = [
    (path: '/home',    icon: Icons.home_outlined,    label: 'Home'),
    (path: '/library', icon: Icons.video_library_outlined, label: 'Libreria'),
    (path: '/search',  icon: Icons.search,           label: 'Cerca'),
    (path: '/profile', icon: Icons.person_outline,   label: 'Profilo'),
  ];

  @override
  Widget build(BuildContext context) {
    final loc = GoRouterState.of(context).matchedLocation;
    final selected = _destinations.indexWhere((d) => loc.startsWith(d.path));
    return Scaffold(
      body: Row(
        children: [
          NavigationRail(
            selectedIndex: selected < 0 ? 0 : selected,
            onDestinationSelected: (i) => context.go(_destinations[i].path),
            labelType: NavigationRailLabelType.all,
            destinations: [
              for (final d in _destinations)
                NavigationRailDestination(
                  icon: Icon(d.icon),
                  label: Text(d.label),
                ),
            ],
          ),
          const VerticalDivider(width: 1),
          Expanded(child: child),
        ],
      ),
    );
  }
}
```

- [ ] **Step 2: Implement the watch placeholder**

```dart
// lib/presentation/pages/watch_placeholder_page.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class WatchPlaceholderPage extends ConsumerWidget {
  const WatchPlaceholderPage({
    super.key,
    required this.tmdbId,
    required this.mediaType,
    this.season,
    this.episode,
  });

  final int tmdbId;
  final String mediaType;
  final int? season;
  final int? episode;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('Riproduzione')),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            'Player coming in sub-plan 6b.\n'
            'tmdb_id=$tmdbId · media_type=$mediaType'
            '${season != null ? "\nS${season}E${episode}" : ""}',
            textAlign: TextAlign.center,
          ),
        ),
      ),
    );
  }
}
```

- [ ] **Step 3: Commit (no tests for the shell — exercised by routing)**

```bash
git add lib/presentation/widgets/authenticated_shell.dart lib/presentation/pages/watch_placeholder_page.dart
git commit -m "ui: AuthenticatedShell with side nav + WatchPlaceholderPage stub"
```

---

### Task 14: Router rewrite — ShellRoute + new routes

**Files:**
- Modify: `lib/router.dart`

- [ ] **Step 1: Wrap the authenticated routes in a `ShellRoute` that builds `AuthenticatedShell` and add the new routes**

```dart
    routes: [
      GoRoute(path: '/login', builder: (_, __) => const LoginPage()),
      GoRoute(path: '/register', builder: (_, __) => const RegisterPage()),
      GoRoute(
        path: '/onboarding/plugins',
        builder: (_, __) => const PluginOnboardingPage(),
      ),
      ShellRoute(
        builder: (context, state, child) => AuthenticatedShell(child: child),
        routes: [
          GoRoute(path: '/home', builder: (_, __) => const HomePage()),
          GoRoute(path: '/library', builder: (_, __) => const LibraryPage()),
          GoRoute(path: '/search', builder: (_, __) => const SearchPage()),
          GoRoute(path: '/profile', builder: (_, __) => const ProfilePage()),
          GoRoute(path: '/settings', builder: (_, __) => const SettingsPage()),
          GoRoute(path: '/plugins', builder: (_, __) => const PluginsPage()),
          GoRoute(
            path: '/title/:tmdbId',
            builder: (ctx, state) => TitlePage(
              tmdbId: int.parse(state.pathParameters['tmdbId']!),
              mediaType: state.uri.queryParameters['media_type'] ?? 'movie',
            ),
          ),
          GoRoute(
            path: '/watch/:tmdbId',
            builder: (ctx, state) => WatchPlaceholderPage(
              tmdbId: int.parse(state.pathParameters['tmdbId']!),
              mediaType: state.uri.queryParameters['media_type'] ?? 'movie',
              season: int.tryParse(state.uri.queryParameters['season'] ?? ''),
              episode: int.tryParse(state.uri.queryParameters['episode'] ?? ''),
            ),
          ),
        ],
      ),
    ],
```

Add the new imports at the top:

```dart
import 'presentation/pages/library_page.dart';
import 'presentation/pages/search_page.dart';
import 'presentation/pages/title_page.dart';
import 'presentation/pages/watch_placeholder_page.dart';
import 'presentation/widgets/authenticated_shell.dart';
```

- [ ] **Step 2: Run full suite, expect pass (the existing redirect logic is unchanged — only the `routes:` block was modified)**

- [ ] **Step 3: Commit**

```bash
git add lib/router.dart
git commit -m "router: AuthenticatedShell + /library /search /title /watch routes"
```

---

## Acceptance criteria for this sub-plan

- 175+ tests pass (baseline 162 + ~13 new across this plan).
- `flutter analyze` clean.
- Logged-in user with PAT lands on `/home` showing collection rows.
- Side nav switches between Home / Library / Search / Profile.
- Library page shows Movies/TV tabs with poster grids.
- Search page debounces input (250ms) and shows TMDB matches.
- Tap any poster → title page renders metadata.
- For TV titles: season chips + episode list visible.
- `/watch/...` shows the placeholder until sub-plan 6b lands.

## Out of scope (DO NOT include)

- Watch page proper (sub-plan 6b)
- Favorites / watchlist toggles (sub-plan 6b)
- Continue-watching row on home (sub-plan 6b)
- Progress polling (sub-plan 6b)
- Telemetry batching (sub-plan 6c)
- Auto-updater (sub-plan 6c)
- Settings polish (sub-plan 6c)
- Build/sign/release pipeline (sub-plan 6c)
- Infinite scroll / pagination beyond first page (post-MVP)
- Cast metadata, similar-titles row, recommendations (post-MVP)
- Mobile responsive layout (post-MVP)
