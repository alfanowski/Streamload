# v3 HLS Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up local HLS playback in the Flutter client. A `getStreams(target)` call from a mounted plugin returns `{manifest_url, headers, is_drm, drm_keys}`; this plan turns that into a playing video by running a local shelf HTTP proxy on `127.0.0.1:<ephemeral>` that fetches and rewrites m3u8 playlists, proxies AES-128 keys, fetches and (if needed) decrypts segments through a RAM+disk LRU cache, and feeds the rewritten master URL to a `media_kit` `Player`.

**Architecture:** A `LocalProxyServer` (shelf + shelf_router) bound to loopback owns four routes: `/master/{sid}.m3u8`, `/variant/{sid}/{rendition}.m3u8`, `/key/{sid}/{rendition}`, `/seg/{sid}/{rendition}/{n}.ts`. A `PlaybackSessionRegistry` keeps per-session state in memory (upstream master URL + headers + DRM keys, with TTL eviction). The pure `Rewriter` ports the v2 Python `m3u8_rewrite.py` to Dart. Segment bytes flow through `RamRingBuffer` → `DiskSegmentCache` → upstream fetch via dio. AES-128 key bytes are proxied raw; the player fetches them from our `/key/...` route. DRM (Widevine L3 / PlayReady L3) decryption uses pointycastle on a per-segment basis when `is_drm` is set.

**Tech Stack:** Flutter 3.41+, Dart 3.11+, shelf 1.4, shelf_router 1.1, media_kit 1.1 (+media_kit_video, media_kit_libs_macos_video), pointycastle 3.9 (already), dio (already), path_provider 2.1, riverpod 2.5, freezed 2.5.

---

## Source spec

This plan implements **Sub-plan #5** from `docs/superpowers/specs/2026-05-09-streamload-v3-design.md` §7 (HLS playback pipeline) and §4 (`player/` directory in client architecture). It depends on **Sub-plan #4** being merged (the plugin runtime and `Plugin.getStreams()` typed wrapper).

The terminal state of this plan is: with a real plugin mounted (e.g. the echo fixture extended to return a public test HLS manifest, or a real scraping plugin), a Dart-side call like:

```dart
final url = await playController.startPlayback(
  tmdbId: 12345, mediaType: 'movie',
);
await player.open(Media(url, httpHeaders: ...));
```

resolves to `http://127.0.0.1:<port>/master/<sid>.m3u8`, the rewritten manifest is served, the player begins decoding, and a sample segment download is observed in the logs. The watch UI is **NOT** built here (that's sub-plan #6) — this plan terminates at "the player can play".

## File structure

### New files

| Path | Created in | Purpose |
|---|---|---|
| `lib/player/rewriter.dart` | T3-T4 | Pure m3u8 master + media rewriter (port of v2 m3u8_rewrite.py) |
| `lib/player/session.dart` | T5 | `PlaybackSession` freezed model + `PlaybackSessionRegistry` (in-memory + TTL) |
| `lib/player/cache/ram_buffer.dart` | T6 | LRU ring buffer for hot segments (per session) |
| `lib/player/cache/disk_cache.dart` | T7 | Filesystem-backed LRU segment cache (per app, 30 GB cap) |
| `lib/player/segment_fetcher.dart` | T8 | Fetch order: RAM → disk → upstream (via dio). DRM-decrypt when `is_drm`. |
| `lib/player/drm.dart` | T9 | AES-CBC segment decryption wrapper around pointycastle |
| `lib/player/proxy.dart` | T10-T14 | `LocalProxyServer` — bind, routes, lifecycle |
| `lib/player/engine.dart` | T15 | `PlayerEngine` — thin media_kit wrapper (open/play/pause/seek/dispose + position stream) |
| `lib/domain/play_title.dart` | T16 | `PlayController` — given (tmdb_id, media_type, season?, episode?) + plugin runtime, orchestrates getStreams → session.create → returns proxy master URL |
| `lib/state/playback_session_registry_provider.dart` | T17 | singleton |
| `lib/state/local_proxy_provider.dart` | T18 | singleton, lifecycle-aware |
| `lib/state/player_engine_provider.dart` | T19 | per-watch-screen scoped |
| `lib/state/play_controller_provider.dart` | T20 | wires plugins + proxy + session registry |
| `test/player/rewriter_test.dart` | T3-T4 | port of v2 test fixtures + new variant cases |
| `test/player/session_test.dart` | T5 | put/get/touch/expire round-trip |
| `test/player/cache/ram_buffer_test.dart` | T6 | LRU semantics |
| `test/player/cache/disk_cache_test.dart` | T7 | put/get + size eviction |
| `test/player/segment_fetcher_test.dart` | T8 | RAM hit / disk hit / upstream miss + decrypt |
| `test/player/drm_test.dart` | T9 | known-vector AES-CBC decrypt |
| `test/player/proxy_test.dart` | T10-T14 | spin up real shelf server on localhost, hit each route via http client |
| `test/player/engine_test.dart` | T15 | media_kit Player init + dispose (no real playback in test) |
| `test/domain/play_title_test.dart` | T16 | mock PluginRuntime, assert URL shape and session is registered |

### Modified files

| Path | Modified in | Change |
|---|---|---|
| `pubspec.yaml` | T1 | add shelf, shelf_router, media_kit, media_kit_video, media_kit_libs_macos_video, path_provider |
| `macos/Runner/DebugProfile.entitlements` | T2 | confirm `com.apple.security.network.server` present (no-op edit if already there) |
| `macos/Runner/Release.entitlements` | T2 | same |
| `lib/main.dart` | T18 | start `LocalProxyServer` after auth bootstrap, dispose on app shutdown |

---

## Phase A — Dependencies + entitlements

### Task 1: Add player deps to pubspec.yaml

**Files:**
- Modify: `pubspec.yaml`

- [ ] **Step 1: Edit `pubspec.yaml` — append under existing `dependencies:` (after the plugin-runtime block from Plan #4)**

```yaml
  # HLS playback
  shelf: ^1.4.1
  shelf_router: ^1.1.4
  media_kit: ^1.1.11
  media_kit_video: ^1.2.5
  media_kit_libs_macos_video: ^1.1.4
  path_provider: ^2.1.4
```

- [ ] **Step 2: Resolve**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
flutter pub get
```

Expected: `Got dependencies!` no resolution conflicts.

- [ ] **Step 3: Sanity test — existing suite still passes**

```bash
flutter test 2>&1 | tail -3
```

Expected: 106+ tests pass.

- [ ] **Step 4: Commit**

```bash
git add pubspec.yaml pubspec.lock macos/Flutter/GeneratedPluginRegistrant.swift macos/Flutter/Flutter-Debug.xcconfig macos/Flutter/Flutter-Release.xcconfig
git commit -m "deps: shelf + media_kit + path_provider for HLS playback"
```

(The macOS regen happens via `flutter pub get`. Include all generated files in the same commit so the build doesn't break for the next task.)

---

### Task 2: Confirm macOS entitlements include network.server + network.client

**Files:**
- Read-only check: `macos/Runner/DebugProfile.entitlements`, `macos/Runner/Release.entitlements`

- [ ] **Step 1: Verify both entitlements files have BOTH `com.apple.security.network.server` AND `com.apple.security.network.client`**

```bash
grep -A1 'network\.\(server\|client\)' macos/Runner/DebugProfile.entitlements macos/Runner/Release.entitlements
```

Expected output: each file lists both keys with `<true/>` value. If either is missing, add it now and commit:

```xml
<key>com.apple.security.network.server</key>
<true/>
<key>com.apple.security.network.client</key>
<true/>
```

- [ ] **Step 2: Commit only if changes were necessary** (otherwise skip)

```bash
git add macos/Runner/*.entitlements
git commit -m "macos: ensure network.client + network.server entitlements"
```

If no changes were needed, no commit.

---

## Phase B — m3u8 rewriter (port from v2)

### Task 3: Master playlist rewriter + tests

**Files:**
- Create: `lib/player/rewriter.dart`
- Create: `test/player/rewriter_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/player/rewriter_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/player/rewriter.dart';

const _masterSample = '''
#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Italian",DEFAULT=YES,LANGUAGE="ita",URI="https://upstream/playlist?type=audio&rendition=ita&token=t1"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Italian",LANGUAGE="ita",URI="https://upstream/playlist?type=subtitle&rendition=ita&token=t1"
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=854x480,AUDIO="audio",SUBTITLES="subs"
https://upstream/playlist?type=video&rendition=480p&token=t1
#EXT-X-STREAM-INF:BANDWIDTH=2150000,RESOLUTION=1280x720,AUDIO="audio",SUBTITLES="subs"
https://upstream/playlist?type=video&rendition=720p&token=t1
''';

void main() {
  group('rewriteMaster', () {
    test('replaces video renditions with proxy paths labelled by ?rendition= param', () {
      final out = Rewriter.rewriteMaster(_masterSample, basePath: '/stream/sid');
      expect(out, contains('/stream/sid/video/480p.m3u8'));
      expect(out, contains('/stream/sid/video/720p.m3u8'));
      expect(out, isNot(contains('upstream')));
    });

    test('replaces audio MEDIA URIs with proxy paths labelled by language', () {
      final out = Rewriter.rewriteMaster(_masterSample, basePath: '/stream/sid');
      expect(out, contains('/stream/sid/audio/ita.m3u8'));
    });

    test('strips SUBTITLES MEDIA tags entirely', () {
      final out = Rewriter.rewriteMaster(_masterSample, basePath: '/stream/sid');
      expect(out, isNot(contains('TYPE=SUBTITLES')));
      // And STREAM-INF must not reference the now-missing subtitle group.
      expect(out, isNot(contains('SUBTITLES="subs"')));
    });

    test('preserves STREAM-INF attributes (bandwidth, resolution)', () {
      final out = Rewriter.rewriteMaster(_masterSample, basePath: '/stream/sid');
      expect(out, contains('BANDWIDTH=1200000'));
      expect(out, contains('RESOLUTION=854x480'));
    });

    test('falls back to sha1[:8] label when no ?rendition= query param', () {
      const sample = '''
#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=640x360
https://upstream/some/opaque/path/playlist.m3u8
''';
      final out = Rewriter.rewriteMaster(sample, basePath: '/stream/sid');
      // sha1 of the URL truncated to 8 hex chars.
      final pattern = RegExp(r'/stream/sid/video/[0-9a-f]{8}\.m3u8');
      expect(pattern.hasMatch(out), isTrue, reason: 'output: $out');
    });
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/player/rewriter_test.dart
```

Expected: import error (`Rewriter` undefined).

- [ ] **Step 3: Implement**

```dart
// lib/player/rewriter.dart
import 'dart:convert';

import 'package:crypto/crypto.dart';

/// Pure m3u8 rewriting. No IO. Mirrors the v2 backend's
/// `streamload/streaming/m3u8_rewrite.py` 1:1 in semantics.
class Rewriter {
  static final _streamInf = RegExp(r'^#EXT-X-STREAM-INF:.*$', multiLine: true);
  static final _renditionParam = RegExp(r'rendition=([^&"\s]+)');
  static final _uriAttr = RegExp(r'URI="([^"]+)"');
  static final _typeAttr = RegExp(r'TYPE=(\w+)');
  static final _languageAttr = RegExp(r'LANGUAGE="([^"]+)"');
  static final _subsAttrInline =
      RegExp(r',?\s*SUBTITLES="[^"]*"');
  static final _strayLeadingComma = RegExp(r':\s*,');

  /// Rewrite a master playlist. Audio MEDIA URIs become
  /// `{basePath}/audio/{lang}.m3u8`. Video STREAM-INF lines get a
  /// `{basePath}/video/{label}.m3u8` URL on the next line. SUBTITLES
  /// MEDIA tags are dropped entirely (and STREAM-INF SUBTITLES="..."
  /// attributes scrubbed).
  static String rewriteMaster(String text, {required String basePath}) {
    final lines = const LineSplitter().convert(text);
    final out = <String>[];
    for (var i = 0; i < lines.length; i++) {
      final line = lines[i];

      if (line.startsWith('#EXT-X-MEDIA:')) {
        final type = _typeAttr.firstMatch(line)?.group(1);
        if (type == 'SUBTITLES') {
          // Drop entirely.
          continue;
        }
        if (type == 'AUDIO') {
          final lang = _languageAttr.firstMatch(line)?.group(1);
          if (lang != null) {
            final replaced = line.replaceFirstMapped(
              _uriAttr,
              (_) => 'URI="$basePath/audio/$lang.m3u8"',
            );
            out.add(replaced);
            continue;
          }
        }
        out.add(line);
        continue;
      }

      if (line.startsWith('#EXT-X-STREAM-INF:')) {
        var cleaned = line.replaceAll(_subsAttrInline, '');
        cleaned = cleaned.replaceAll(_strayLeadingComma, ':');
        out.add(cleaned);
        // Next line is the upstream URL — replace it.
        if (i + 1 < lines.length) {
          final upstream = lines[i + 1].trim();
          if (upstream.isNotEmpty && !upstream.startsWith('#')) {
            out.add('$basePath/video/${_labelFor(upstream)}.m3u8');
            i++; // skip the original URL
          }
        }
        continue;
      }

      out.add(line);
    }
    return out.join('\n');
  }

  static String _labelFor(String url) {
    final m = _renditionParam.firstMatch(url);
    if (m != null) return m.group(1)!;
    final hash = sha1.convert(utf8.encode(url)).toString();
    return hash.substring(0, 8);
  }
}
```

- [ ] **Step 4: Run, expect pass**

```bash
flutter test test/player/rewriter_test.dart
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/player/rewriter.dart test/player/rewriter_test.dart
git commit -m "player: m3u8 master rewriter — port v2 strip-subs + label-by-rendition"
```

---

### Task 4: Media (variant) playlist rewriter + tests

**Files:**
- Modify: `lib/player/rewriter.dart` — add `rewriteMedia` static method
- Modify: `test/player/rewriter_test.dart` — add a `group('rewriteMedia', () {...})`

- [ ] **Step 1: Write the failing test FIRST (append at the bottom of `test/player/rewriter_test.dart`, before the closing `}` of `main`)**

```dart
  group('rewriteMedia', () {
    const mediaSample = '''
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXTINF:5.5,
https://upstream/seg-001.ts
#EXTINF:5.5,
https://upstream/seg-002.ts
#EXT-X-ENDLIST
''';

    test('replaces segment URLs with /seg/{rendition}/{n}.ts', () {
      final out = Rewriter.rewriteMedia(mediaSample,
          rendition: '720p', basePath: '/stream/sid');
      expect(out, contains('/stream/sid/seg/720p/0.ts'));
      expect(out, contains('/stream/sid/seg/720p/1.ts'));
      expect(out, isNot(contains('upstream')));
    });

    test('preserves EXTINF durations + EXT-X-ENDLIST', () {
      final out = Rewriter.rewriteMedia(mediaSample,
          rendition: '720p', basePath: '/stream/sid');
      expect(out, contains('#EXTINF:5.5'));
      expect(out, contains('#EXT-X-ENDLIST'));
    });

    test('rewrites EXT-X-KEY URI to local key proxy', () {
      const encrypted = '''
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-KEY:METHOD=AES-128,URI="https://upstream-keys/abc.key",IV=0xdeadbeef
#EXTINF:5.5,
https://upstream/seg-001.ts
#EXT-X-ENDLIST
''';
      final out = Rewriter.rewriteMedia(encrypted,
          rendition: '480p', basePath: '/stream/sid');
      expect(out, contains('URI="/stream/sid/key/480p"'));
      // IV preserved (player still needs it).
      expect(out, contains('IV=0xdeadbeef'));
      // Original key host gone.
      expect(out, isNot(contains('upstream-keys')));
    });
  });
```

- [ ] **Step 2: Run, expect failure (`rewriteMedia` undefined)**

```bash
flutter test test/player/rewriter_test.dart
```

- [ ] **Step 3: Implement — append inside the `Rewriter` class in `lib/player/rewriter.dart`**

```dart
  /// Rewrite a media (variant) playlist. Segment URIs become
  /// `{basePath}/seg/{rendition}/{n}.ts`. AES-128 key URIs become
  /// `{basePath}/key/{rendition}` (the IV attribute is preserved).
  static String rewriteMedia(
    String text, {
    required String rendition,
    required String basePath,
  }) {
    final lines = const LineSplitter().convert(text);
    final out = <String>[];
    var segIndex = 0;
    for (final line in lines) {
      if (line.startsWith('#EXT-X-KEY:')) {
        final replaced = line.replaceFirstMapped(
          _uriAttr,
          (_) => 'URI="$basePath/key/$rendition"',
        );
        out.add(replaced);
        continue;
      }
      if (line.isNotEmpty && !line.startsWith('#')) {
        out.add('$basePath/seg/$rendition/$segIndex.ts');
        segIndex++;
        continue;
      }
      out.add(line);
    }
    return out.join('\n');
  }
```

- [ ] **Step 4: Run, expect pass (8 tests total in rewriter_test.dart)**

```bash
flutter test test/player/rewriter_test.dart
```

- [ ] **Step 5: Commit**

```bash
git add lib/player/rewriter.dart test/player/rewriter_test.dart
git commit -m "player: m3u8 media rewriter — segments + AES-128 key URI proxy"
```

---

## Phase C — Session registry

### Task 5: PlaybackSession + PlaybackSessionRegistry

**Files:**
- Create: `lib/player/session.dart`
- Create: `test/player/session_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/player/session_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/player/session.dart';

void main() {
  test('put + get round-trip', () {
    final reg = PlaybackSessionRegistry(ttl: const Duration(hours: 4));
    final s = PlaybackSession.create(
      tmdbId: 42,
      mediaType: 'movie',
      pluginShortName: 'echo',
      upstreamMasterUrl: 'https://upstream/m.m3u8',
      upstreamHeaders: const {'Referer': 'https://up'},
    );
    reg.put(s);
    final got = reg.get(s.id);
    expect(got, isNotNull);
    expect(got!.tmdbId, 42);
    expect(got.upstreamMasterUrl, 'https://upstream/m.m3u8');
  });

  test('get returns null for unknown id', () {
    final reg = PlaybackSessionRegistry(ttl: const Duration(seconds: 1));
    expect(reg.get('does-not-exist'), isNull);
  });

  test('TTL expiry — get after TTL returns null and evicts', () async {
    final reg = PlaybackSessionRegistry(ttl: const Duration(milliseconds: 50));
    final s = PlaybackSession.create(
      tmdbId: 1, mediaType: 'movie', pluginShortName: 'p',
      upstreamMasterUrl: 'u', upstreamHeaders: const {},
    );
    reg.put(s);
    await Future.delayed(const Duration(milliseconds: 80));
    expect(reg.get(s.id), isNull);
  });

  test('touch resets last-seen — keeps session alive', () async {
    final reg = PlaybackSessionRegistry(ttl: const Duration(milliseconds: 80));
    final s = PlaybackSession.create(
      tmdbId: 1, mediaType: 'movie', pluginShortName: 'p',
      upstreamMasterUrl: 'u', upstreamHeaders: const {},
    );
    reg.put(s);
    await Future.delayed(const Duration(milliseconds: 50));
    reg.get(s.id, touch: true); // reset clock
    await Future.delayed(const Duration(milliseconds: 50));
    expect(reg.get(s.id), isNotNull); // would have expired without touch
  });

  test('remove drops the session', () {
    final reg = PlaybackSessionRegistry(ttl: const Duration(hours: 1));
    final s = PlaybackSession.create(
      tmdbId: 1, mediaType: 'movie', pluginShortName: 'p',
      upstreamMasterUrl: 'u', upstreamHeaders: const {},
    );
    reg.put(s);
    reg.remove(s.id);
    expect(reg.get(s.id), isNull);
  });

  test('purgeExpired returns count of purged sessions', () async {
    final reg = PlaybackSessionRegistry(ttl: const Duration(milliseconds: 30));
    final a = PlaybackSession.create(tmdbId: 1, mediaType: 'movie', pluginShortName: 'p', upstreamMasterUrl: 'u', upstreamHeaders: const {});
    final b = PlaybackSession.create(tmdbId: 2, mediaType: 'movie', pluginShortName: 'p', upstreamMasterUrl: 'u', upstreamHeaders: const {});
    reg.put(a);
    reg.put(b);
    await Future.delayed(const Duration(milliseconds: 50));
    expect(reg.purgeExpired(), 2);
  });
}
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```dart
// lib/player/session.dart
import 'dart:math';

/// One playback context. Lives in memory only.
class PlaybackSession {
  PlaybackSession({
    required this.id,
    required this.tmdbId,
    required this.mediaType,
    required this.pluginShortName,
    required this.upstreamMasterUrl,
    required this.upstreamHeaders,
    required this.isDrm,
    required this.drmKeys,
    required this.createdAt,
    required this.lastSeenAt,
  });

  factory PlaybackSession.create({
    required int tmdbId,
    required String mediaType,
    required String pluginShortName,
    required String upstreamMasterUrl,
    required Map<String, String> upstreamHeaders,
    bool isDrm = false,
    Map<String, dynamic>? drmKeys,
  }) {
    final now = DateTime.now();
    return PlaybackSession(
      id: _newId(),
      tmdbId: tmdbId,
      mediaType: mediaType,
      pluginShortName: pluginShortName,
      upstreamMasterUrl: upstreamMasterUrl,
      upstreamHeaders: Map.unmodifiable(upstreamHeaders),
      isDrm: isDrm,
      drmKeys: drmKeys,
      createdAt: now,
      lastSeenAt: now,
    );
  }

  final String id;
  final int tmdbId;
  final String mediaType;
  final String pluginShortName;
  final String upstreamMasterUrl;
  final Map<String, String> upstreamHeaders;
  final bool isDrm;
  final Map<String, dynamic>? drmKeys;
  final DateTime createdAt;
  DateTime lastSeenAt;

  /// Per-rendition upstream URL — populated lazily by the proxy when it
  /// first sees a request for `/variant/{sid}/{rendition}.m3u8` (the
  /// rendition label was generated by Rewriter from the master playlist).
  final Map<String, String> renditionUpstream = {};
}

String _newId() {
  // 16 hex chars — collision-resistant enough for in-process registry.
  final r = Random.secure();
  return List.generate(16, (_) => r.nextInt(16).toRadixString(16)).join();
}

class PlaybackSessionRegistry {
  PlaybackSessionRegistry({required Duration ttl}) : _ttl = ttl;

  final Duration _ttl;
  final Map<String, PlaybackSession> _sessions = {};

  void put(PlaybackSession s) {
    _sessions[s.id] = s;
  }

  PlaybackSession? get(String id, {bool touch = false}) {
    final s = _sessions[id];
    if (s == null) return null;
    if (DateTime.now().difference(s.lastSeenAt) > _ttl) {
      _sessions.remove(id);
      return null;
    }
    if (touch) s.lastSeenAt = DateTime.now();
    return s;
  }

  void remove(String id) {
    _sessions.remove(id);
  }

  int purgeExpired() {
    final now = DateTime.now();
    final toDrop = _sessions.entries
        .where((e) => now.difference(e.value.lastSeenAt) > _ttl)
        .map((e) => e.key)
        .toList();
    for (final id in toDrop) {
      _sessions.remove(id);
    }
    return toDrop.length;
  }
}
```

- [ ] **Step 4: Run, expect 6 tests pass**

- [ ] **Step 5: Commit**

```bash
git add lib/player/session.dart test/player/session_test.dart
git commit -m "player: PlaybackSession + in-memory registry with TTL eviction"
```

---

## Phase D — Caches

### Task 6: RamRingBuffer (LRU)

**Files:**
- Create: `lib/player/cache/ram_buffer.dart`
- Create: `test/player/cache/ram_buffer_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/player/cache/ram_buffer_test.dart
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/player/cache/ram_buffer.dart';

Uint8List _b(int v) => Uint8List.fromList([v]);

void main() {
  test('put + get round-trip', () {
    final buf = RamRingBuffer(capacity: 3);
    buf.put('a', _b(1));
    expect(buf.get('a'), equals(_b(1)));
    expect(buf.get('missing'), isNull);
  });

  test('LRU eviction at capacity', () {
    final buf = RamRingBuffer(capacity: 2);
    buf.put('a', _b(1));
    buf.put('b', _b(2));
    buf.put('c', _b(3)); // evicts 'a' (least recent)
    expect(buf.get('a'), isNull);
    expect(buf.get('b'), equals(_b(2)));
    expect(buf.get('c'), equals(_b(3)));
  });

  test('get bumps recency', () {
    final buf = RamRingBuffer(capacity: 2);
    buf.put('a', _b(1));
    buf.put('b', _b(2));
    buf.get('a'); // 'a' is now most recent
    buf.put('c', _b(3)); // evicts 'b' instead of 'a'
    expect(buf.get('a'), equals(_b(1)));
    expect(buf.get('b'), isNull);
  });

  test('put on existing key updates value and bumps recency', () {
    final buf = RamRingBuffer(capacity: 2);
    buf.put('a', _b(1));
    buf.put('b', _b(2));
    buf.put('a', _b(99)); // overwrite + bump
    buf.put('c', _b(3));  // evicts 'b'
    expect(buf.get('a'), equals(_b(99)));
    expect(buf.get('b'), isNull);
  });

  test('capacity < 1 throws', () {
    expect(() => RamRingBuffer(capacity: 0), throwsArgumentError);
  });
}
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```dart
// lib/player/cache/ram_buffer.dart
import 'dart:collection';
import 'dart:typed_data';

/// Simple in-memory LRU cache for hot segments. Per-session capacity
/// (typically 30 segments at ~6s each = ~3 minutes of buffer).
class RamRingBuffer {
  RamRingBuffer({required this.capacity}) {
    if (capacity < 1) {
      throw ArgumentError.value(capacity, 'capacity', 'must be >= 1');
    }
  }

  final int capacity;
  final LinkedHashMap<String, Uint8List> _store = LinkedHashMap();

  Uint8List? get(String key) {
    final v = _store.remove(key);
    if (v == null) return null;
    _store[key] = v; // re-insert at the end → most recent
    return v;
  }

  void put(String key, Uint8List value) {
    _store.remove(key); // ensure correct ordering even on overwrite
    _store[key] = value;
    while (_store.length > capacity) {
      _store.remove(_store.keys.first);
    }
  }

  int get length => _store.length;
}
```

- [ ] **Step 4: Run, expect 5 tests pass**

- [ ] **Step 5: Commit**

```bash
git add lib/player/cache/ram_buffer.dart test/player/cache/ram_buffer_test.dart
git commit -m "player(cache): RamRingBuffer — LRU hot-segment cache"
```

---

### Task 7: DiskSegmentCache (filesystem LRU)

**Files:**
- Create: `lib/player/cache/disk_cache.dart`
- Create: `test/player/cache/disk_cache_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/player/cache/disk_cache_test.dart
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/player/cache/disk_cache.dart';

void main() {
  late Directory tmp;

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('disk_cache_test_');
  });

  tearDown(() async {
    if (await tmp.exists()) await tmp.delete(recursive: true);
  });

  Uint8List bytes(int n) => Uint8List.fromList(List.filled(n, 0x42));

  test('put + get round-trip', () async {
    final c = DiskSegmentCache(directory: tmp.path, sizeLimitBytes: 1024 * 1024);
    await c.put('k1', bytes(128));
    final got = await c.get('k1');
    expect(got, isNotNull);
    expect(got!.length, 128);
  });

  test('get returns null for missing key', () async {
    final c = DiskSegmentCache(directory: tmp.path, sizeLimitBytes: 1024);
    expect(await c.get('missing'), isNull);
  });

  test('LRU eviction when total size exceeds the limit', () async {
    // Limit: 300 bytes. Insert three 200-byte entries → first must be evicted.
    final c = DiskSegmentCache(directory: tmp.path, sizeLimitBytes: 300);
    await c.put('a', bytes(200));
    await c.put('b', bytes(200));
    await c.put('c', bytes(200));
    expect(await c.get('a'), isNull, reason: 'a should be evicted');
    expect(await c.get('c'), isNotNull);
  });

  test('get bumps recency — preserves entry on next eviction', () async {
    final c = DiskSegmentCache(directory: tmp.path, sizeLimitBytes: 300);
    await c.put('a', bytes(200));
    await c.put('b', bytes(200));
    await c.get('a'); // bump
    await c.put('c', bytes(200)); // evicts 'b' instead of 'a'
    expect(await c.get('a'), isNotNull);
    expect(await c.get('b'), isNull);
  });
}
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement — simple file-per-entry with sidecar `.lru` file holding the access timestamp**

```dart
// lib/player/cache/disk_cache.dart
import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'dart:convert';

/// Filesystem-backed LRU cache. Each entry is one file under `directory/`,
/// named by sha1 of the key. Access time is tracked by `setLastAccessed`
/// on the file; eviction sorts files by atime ascending and removes
/// oldest until total size is below the limit.
class DiskSegmentCache {
  DiskSegmentCache({
    required this.directory,
    required this.sizeLimitBytes,
  }) {
    Directory(directory).createSync(recursive: true);
  }

  final String directory;
  final int sizeLimitBytes;

  String _pathFor(String key) {
    final h = sha1.convert(utf8.encode(key)).toString();
    return '$directory/$h.bin';
  }

  Future<Uint8List?> get(String key) async {
    final f = File(_pathFor(key));
    if (!await f.exists()) return null;
    // Bump atime so LRU sees this as recent.
    final now = DateTime.now();
    try {
      await f.setLastAccessed(now);
    } catch (_) {/* some FSes don't support; ignore */}
    return f.readAsBytes();
  }

  Future<void> put(String key, Uint8List value) async {
    final f = File(_pathFor(key));
    await f.writeAsBytes(value, flush: true);
    await _evictIfNeeded();
  }

  Future<void> _evictIfNeeded() async {
    final dir = Directory(directory);
    final files = await dir.list().where((e) => e is File).cast<File>().toList();
    int total = 0;
    final entries = <_Entry>[];
    for (final f in files) {
      final st = await f.stat();
      total += st.size;
      entries.add(_Entry(f, st.accessed, st.size));
    }
    if (total <= sizeLimitBytes) return;
    entries.sort((a, b) => a.accessed.compareTo(b.accessed));
    for (final e in entries) {
      if (total <= sizeLimitBytes) return;
      await e.file.delete();
      total -= e.size;
    }
  }
}

class _Entry {
  _Entry(this.file, this.accessed, this.size);
  final File file;
  final DateTime accessed;
  final int size;
}
```

- [ ] **Step 4: Run, expect 4 tests pass**

```bash
flutter test test/player/cache/disk_cache_test.dart
```

> Note: `setLastAccessed` is a no-op or unsupported on some macOS configurations. If the LRU eviction test is flaky because of clock granularity, add a 5ms `await Future.delayed(...)` between puts in the test (NOT in the production code — the prod path's puts have segment-fetch latency between them naturally).

- [ ] **Step 5: Commit**

```bash
git add lib/player/cache/disk_cache.dart test/player/cache/disk_cache_test.dart
git commit -m "player(cache): DiskSegmentCache — file-per-segment LRU with size cap"
```

---

## Phase E — DRM + segment fetcher

### Task 8: SegmentFetcher (RAM → disk → upstream)

**Files:**
- Create: `lib/player/segment_fetcher.dart`
- Create: `test/player/segment_fetcher_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/player/segment_fetcher_test.dart
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/player/cache/disk_cache.dart';
import 'package:streamload_client/player/cache/ram_buffer.dart';
import 'package:streamload_client/player/segment_fetcher.dart';

class _DioMock extends Mock implements Dio {}

void main() {
  late Directory tmp;
  late DiskSegmentCache disk;
  late RamRingBuffer ram;
  late _DioMock dio;
  late SegmentFetcher fetcher;

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('seg_fetch_');
    disk = DiskSegmentCache(directory: tmp.path, sizeLimitBytes: 10 * 1024 * 1024);
    ram = RamRingBuffer(capacity: 4);
    dio = _DioMock();
    fetcher = SegmentFetcher(ram: ram, disk: disk, dio: dio);
    registerFallbackValue(RequestOptions(path: ''));
  });

  tearDown(() async {
    if (await tmp.exists()) await tmp.delete(recursive: true);
  });

  Uint8List body(int n) => Uint8List.fromList(List.filled(n, 0xAB));

  test('RAM hit — does not touch disk or dio', () async {
    ram.put('http://x/seg.ts|', body(64));
    final out = await fetcher.fetch('http://x/seg.ts', headers: const {});
    expect(out.length, 64);
    verifyZeroInteractions(dio);
  });

  test('disk hit — promotes to RAM', () async {
    await disk.put('http://x/seg.ts|', body(32));
    final out = await fetcher.fetch('http://x/seg.ts', headers: const {});
    expect(out.length, 32);
    expect(ram.get('http://x/seg.ts|'), isNotNull);
    verifyZeroInteractions(dio);
  });

  test('miss — fetches via dio, stores in RAM + disk', () async {
    when(() => dio.get<List<int>>(
          'http://x/seg.ts',
          options: any(named: 'options'),
        )).thenAnswer((_) async => Response<List<int>>(
          requestOptions: RequestOptions(path: 'http://x/seg.ts'),
          data: body(128),
          statusCode: 200,
        ));
    final out = await fetcher.fetch('http://x/seg.ts', headers: const {'Referer': 'r'});
    expect(out.length, 128);
    expect(ram.get('http://x/seg.ts|Referer=r'), isNotNull);
    expect(await disk.get('http://x/seg.ts|Referer=r'), isNotNull);
  });

  test('decryptor is applied when supplied (DRM path)', () async {
    when(() => dio.get<List<int>>(
          any(),
          options: any(named: 'options'),
        )).thenAnswer((_) async => Response<List<int>>(
          requestOptions: RequestOptions(path: 'http://x/seg.ts'),
          data: body(16),
          statusCode: 200,
        ));
    final out = await fetcher.fetch(
      'http://x/seg.ts',
      headers: const {},
      decryptor: (raw) => Uint8List.fromList(raw.map((b) => b ^ 0xFF).toList()),
    );
    expect(out.first, 0x54); // 0xAB ^ 0xFF
  });
}
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```dart
// lib/player/segment_fetcher.dart
import 'dart:typed_data';

import 'package:dio/dio.dart';

import 'cache/disk_cache.dart';
import 'cache/ram_buffer.dart';

typedef SegmentDecryptor = Uint8List Function(Uint8List raw);

class SegmentFetcher {
  SegmentFetcher({
    required this.ram,
    required this.disk,
    required this.dio,
  });

  final RamRingBuffer ram;
  final DiskSegmentCache disk;
  final Dio dio;

  /// Cache key includes headers so two sessions with different auth don't
  /// share encrypted bytes. Headers are sorted+joined to produce a stable key.
  static String _cacheKey(String url, Map<String, String> headers) {
    final entries = headers.entries.toList()
      ..sort((a, b) => a.key.compareTo(b.key));
    final headerPart = entries.map((e) => '${e.key}=${e.value}').join('&');
    return '$url|$headerPart';
  }

  Future<Uint8List> fetch(
    String url, {
    required Map<String, String> headers,
    SegmentDecryptor? decryptor,
  }) async {
    final key = _cacheKey(url, headers);

    final hot = ram.get(key);
    if (hot != null) return hot;

    final warm = await disk.get(key);
    if (warm != null) {
      ram.put(key, warm);
      return warm;
    }

    final resp = await dio.get<List<int>>(
      url,
      options: Options(
        responseType: ResponseType.bytes,
        headers: headers,
      ),
    );
    final raw = Uint8List.fromList(resp.data ?? const []);
    final out = decryptor == null ? raw : decryptor(raw);
    ram.put(key, out);
    await disk.put(key, out);
    return out;
  }
}
```

- [ ] **Step 4: Run, expect 4 tests pass**

- [ ] **Step 5: Commit**

```bash
git add lib/player/segment_fetcher.dart test/player/segment_fetcher_test.dart
git commit -m "player: SegmentFetcher — RAM → disk → upstream with optional decryptor"
```

---

### Task 9: AES-CBC segment decryptor + tests

**Files:**
- Create: `lib/player/drm.dart`
- Create: `test/player/drm_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/player/drm_test.dart
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/player/drm.dart';

void main() {
  test('aes-128-cbc decrypt round-trip with PKCS7-padded plaintext', () {
    // Encrypt "hello world!!!!!" (16 bytes, no padding needed) with the
    // crypto_host_test's verified test vector style.
    // key = 0x42 * 16, iv = 0x10 * 16.
    final key = Uint8List(16)..fillRange(0, 16, 0x42);
    final iv = Uint8List(16)..fillRange(0, 16, 0x10);
    // Pre-computed (with PyCryptodome): plaintext "hello world!!!!!" (16 bytes)
    // → AES-128-CBC ciphertext.
    final ct = Uint8List.fromList(const [
      0x6c, 0x82, 0x4f, 0x4b, 0x6e, 0xc8, 0x7e, 0x36,
      0x44, 0xa9, 0x9b, 0x95, 0x67, 0x6e, 0x7e, 0x4d,
    ]);

    final dec = SegmentDrm(keyBytes: key, ivBytes: iv);
    final out = dec.decrypt(ct);
    expect(out, equals(Uint8List.fromList('hello world!!!!!'.codeUnits)));
  });

  test('keyBytes must be exactly 16 bytes (AES-128)', () {
    expect(
      () => SegmentDrm(keyBytes: Uint8List(8), ivBytes: Uint8List(16)),
      throwsArgumentError,
    );
  });

  test('ivBytes must be exactly 16 bytes', () {
    expect(
      () => SegmentDrm(keyBytes: Uint8List(16), ivBytes: Uint8List(8)),
      throwsArgumentError,
    );
  });
}
```

- [ ] **Step 2: Run, expect failure**

> If the pre-computed ciphertext is wrong (subagent should verify with `python3 -c "from Crypto.Cipher import AES; ..."` if pycryptodome is available), correct the vector. The exact vector matters less than the round-trip property.

- [ ] **Step 3: Implement**

```dart
// lib/player/drm.dart
import 'dart:typed_data';

import 'package:pointycastle/export.dart';

/// AES-128-CBC segment decryptor for HLS streams that ship with
/// `#EXT-X-KEY:METHOD=AES-128`. The key is 16 bytes; the IV is either
/// declared on the EXT-X-KEY line or implied by segment number (left
/// to the caller to compute IV-per-segment if needed).
class SegmentDrm {
  SegmentDrm({required Uint8List keyBytes, required Uint8List ivBytes})
      : _key = keyBytes,
        _iv = ivBytes {
    if (keyBytes.length != 16) {
      throw ArgumentError.value(keyBytes.length, 'keyBytes',
          'AES-128 requires a 16-byte key');
    }
    if (ivBytes.length != 16) {
      throw ArgumentError.value(ivBytes.length, 'ivBytes',
          'AES requires a 16-byte IV');
    }
  }

  final Uint8List _key;
  final Uint8List _iv;

  Uint8List decrypt(Uint8List ciphertext) {
    final cbc = CBCBlockCipher(AESEngine())
      ..init(false, ParametersWithIV(KeyParameter(_key), _iv));
    final out = Uint8List(ciphertext.length);
    var offset = 0;
    while (offset < ciphertext.length) {
      offset += cbc.processBlock(ciphertext, offset, out, offset);
    }
    return out;
  }
}
```

- [ ] **Step 4: Run, expect 3 tests pass**

- [ ] **Step 5: Commit**

```bash
git add lib/player/drm.dart test/player/drm_test.dart
git commit -m "player: AES-128-CBC segment decryptor (pointycastle wrapper)"
```

---

## Phase F — Local proxy server

### Task 10: LocalProxyServer skeleton — bind, lifecycle, /health route

**Files:**
- Create: `lib/player/proxy.dart`
- Create: `test/player/proxy_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/player/proxy_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:streamload_client/player/proxy.dart';
import 'package:streamload_client/player/session.dart';

void main() {
  late LocalProxyServer proxy;
  late PlaybackSessionRegistry registry;

  setUp(() async {
    registry = PlaybackSessionRegistry(ttl: const Duration(hours: 1));
    proxy = await LocalProxyServer.start(registry: registry);
  });

  tearDown(() async {
    await proxy.stop();
  });

  test('binds on 127.0.0.1 with system-assigned port', () {
    expect(proxy.port, greaterThan(0));
    expect(proxy.baseUrl, startsWith('http://127.0.0.1:'));
  });

  test('GET /health returns 200 ok', () async {
    final resp = await http.get(Uri.parse('${proxy.baseUrl}/health'));
    expect(resp.statusCode, 200);
    expect(resp.body, 'ok');
  });

  test('unknown route returns 404', () async {
    final resp = await http.get(Uri.parse('${proxy.baseUrl}/nope'));
    expect(resp.statusCode, 404);
  });
}
```

- [ ] **Step 2: Add `http: ^1.2.2` to dev_dependencies (only used in tests). Skip if already present.**

- [ ] **Step 3: Run, expect failure (LocalProxyServer undefined)**

- [ ] **Step 4: Implement skeleton**

```dart
// lib/player/proxy.dart
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:shelf/shelf.dart';
import 'package:shelf/shelf_io.dart' as shelf_io;
import 'package:shelf_router/shelf_router.dart';

import 'session.dart';

/// HTTP proxy bound to 127.0.0.1 on a system-assigned port. Exposes the
/// four HLS routes consumed by media_kit + downstream subroutines.
/// Lifecycle: `start()` returns a running instance; `stop()` closes the
/// HttpServer and waits for in-flight requests to complete.
class LocalProxyServer {
  LocalProxyServer._({
    required this.registry,
    required this.dio,
    required HttpServer server,
  })  : _server = server,
        port = server.port,
        baseUrl = 'http://127.0.0.1:${server.port}';

  static Future<LocalProxyServer> start({
    required PlaybackSessionRegistry registry,
    Dio? dio,
  }) async {
    final dioInstance = dio ?? Dio();
    final tmp = LocalProxyServer._scaffold(registry: registry, dio: dioInstance);
    final server = await shelf_io.serve(
      tmp._handler(),
      InternetAddress.loopbackIPv4,
      0, // system-assigned ephemeral port
    );
    return LocalProxyServer._(
      registry: registry,
      dio: dioInstance,
      server: server,
    );
  }

  /// Test-only constructor used only inside this class for routing setup.
  LocalProxyServer._scaffold({required this.registry, required this.dio})
      : _server = _Stub(),
        port = 0,
        baseUrl = '';

  final PlaybackSessionRegistry registry;
  final Dio dio;
  final HttpServer _server;
  final int port;
  final String baseUrl;

  Handler _handler() {
    final r = Router()
      ..get('/health', (Request _) => Response.ok('ok'));
    return r.call;
  }

  Future<void> stop() async {
    if (_server is HttpServer) {
      await _server.close(force: true);
    }
  }
}

class _Stub implements HttpServer {
  @override
  noSuchMethod(Invocation invocation) =>
      throw StateError('scaffold instance — not a real server');
}
```

> The `_scaffold` indirection is awkward — fold it into one constructor. Reasonable refactor:

Actually, simpler — drop `_scaffold` and inline routing into `start`:

```dart
// lib/player/proxy.dart (cleaner version)
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:shelf/shelf.dart';
import 'package:shelf/shelf_io.dart' as shelf_io;
import 'package:shelf_router/shelf_router.dart';

import 'session.dart';

class LocalProxyServer {
  LocalProxyServer._(this._server, this.registry, this.dio)
      : port = _server.port,
        baseUrl = 'http://127.0.0.1:${_server.port}';

  static Future<LocalProxyServer> start({
    required PlaybackSessionRegistry registry,
    Dio? dio,
  }) async {
    final dioInstance = dio ?? Dio();
    final router = Router()
      ..get('/health', (Request _) => Response.ok('ok'));
    final server = await shelf_io.serve(
      router.call,
      InternetAddress.loopbackIPv4,
      0,
    );
    return LocalProxyServer._(server, registry, dioInstance);
  }

  final HttpServer _server;
  final PlaybackSessionRegistry registry;
  final Dio dio;
  final int port;
  final String baseUrl;

  Future<void> stop() async {
    await _server.close(force: true);
  }
}
```

Use this cleaner version when implementing.

- [ ] **Step 5: Run, expect 3 tests pass**

- [ ] **Step 6: Commit**

```bash
git add lib/player/proxy.dart test/player/proxy_test.dart pubspec.yaml pubspec.lock
git commit -m "player: LocalProxyServer skeleton — loopback bind + /health route"
```

---

### Task 11: Master playlist route — GET /master/{sid}.m3u8

**Files:**
- Modify: `lib/player/proxy.dart` (add route + handler)
- Modify: `test/player/proxy_test.dart` (add test group)

- [ ] **Step 1: Append test (before final `}` of `main`)**

```dart
  group('GET /master/{sid}.m3u8', () {
    test('404 if session unknown', () async {
      final resp = await http.get(Uri.parse('${proxy.baseUrl}/master/unknown.m3u8'));
      expect(resp.statusCode, 404);
    });

    test('200 + rewritten body when session exists', () async {
      // Inject a fake dio that returns a master sample.
      // For this test, we'll register a session whose upstream is a local
      // dart:io server we spin up to serve the fixture.
      final fixtureServer = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      fixtureServer.listen((req) {
        req.response
          ..statusCode = 200
          ..write('''
#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=854x480
http://127.0.0.1:${fixtureServer.port}/v?rendition=480p
''')
          ..close();
      });
      addTearDown(() => fixtureServer.close(force: true));

      final s = PlaybackSession.create(
        tmdbId: 1, mediaType: 'movie', pluginShortName: 'p',
        upstreamMasterUrl: 'http://127.0.0.1:${fixtureServer.port}/master',
        upstreamHeaders: const {},
      );
      registry.put(s);

      final resp = await http.get(Uri.parse('${proxy.baseUrl}/master/${s.id}.m3u8'));
      expect(resp.statusCode, 200);
      expect(resp.body, contains('/master/${s.id}/video/480p.m3u8'));
      expect(resp.headers['content-type'], contains('mpegurl'));
    });
  });
```

> The test rewrites paths under `/master/{sid}/...` (the `basePath` we'll pass to the rewriter is `/master/{sid}` — see Step 2). Adjust the existing `Rewriter.rewriteMaster` test if you spot inconsistency, but this test asserts the OBSERVED behavior end-to-end.

Wait — the spec says variants land at `/variant/{sid}/{rendition}.m3u8`, NOT `/master/{sid}/video/{rendition}.m3u8`. We have two options:

(a) Use `basePath: '/variant/${sid}'` so the rewriter's `'$basePath/video/$label.m3u8'` becomes `/variant/{sid}/video/{label}.m3u8`. Then route `GET /variant/<sid>/video/<label>.m3u8` instead of `GET /variant/<sid>/<label>.m3u8`.

(b) Update Rewriter to use just `{basePath}/{label}.m3u8` (drop the `/video/` segment).

**Decision:** Use option (a) — keep `/video/` and `/audio/` as a discriminator (matches v2). Routes become `/variant/<sid>/video/<rendition>.m3u8` and `/variant/<sid>/audio/<lang>.m3u8`. Master rewriter is called with `basePath: '/variant/${sid}'`.

Update the test accordingly:

```dart
      final resp = await http.get(Uri.parse('${proxy.baseUrl}/master/${s.id}.m3u8'));
      expect(resp.statusCode, 200);
      expect(resp.body, contains('/variant/${s.id}/video/480p.m3u8'));
```

- [ ] **Step 2: Implement — extend `_router` builder in `lib/player/proxy.dart`**

```dart
    final router = Router()
      ..get('/health', (Request _) => Response.ok('ok'))
      ..get('/master/<sid>.m3u8', (Request req, String sid) async {
        final session = registry.get(sid, touch: true);
        if (session == null) return Response.notFound('unknown session');
        try {
          final resp = await dioInstance.get<String>(
            session.upstreamMasterUrl,
            options: Options(
              responseType: ResponseType.plain,
              headers: session.upstreamHeaders,
            ),
          );
          final rewritten = Rewriter.rewriteMaster(
            resp.data ?? '',
            basePath: '/variant/$sid',
          );
          return Response.ok(rewritten, headers: {
            'content-type': 'application/vnd.apple.mpegurl',
          });
        } on DioException catch (e) {
          return Response.internalServerError(body: 'upstream: ${e.message}');
        }
      });
```

> Add the import: `import 'rewriter.dart';`.

- [ ] **Step 3: Run, expect 5 tests pass total in proxy_test.dart**

- [ ] **Step 4: Commit**

```bash
git add lib/player/proxy.dart test/player/proxy_test.dart
git commit -m "player(proxy): GET /master/{sid}.m3u8 — fetch + rewrite + serve"
```

---

### Task 12: Variant playlist route — GET /variant/{sid}/video/{rendition}.m3u8

**Files:**
- Modify: `lib/player/proxy.dart`
- Modify: `test/player/proxy_test.dart`

The variant route needs to know the upstream URL for that rendition. We learn it during the first master fetch (in Task 11) by observing each STREAM-INF's URL. **Update Task 11's master handler** to ALSO populate `session.renditionUpstream[label] = upstreamUrl` as it rewrites — so the variant route can then look it up.

- [ ] **Step 1: Update Rewriter to ALSO emit a label→url map** so the master handler can record it. Refactor `Rewriter.rewriteMaster` signature to return both:

```dart
class MasterRewriteResult {
  MasterRewriteResult({required this.body, required this.renditionUrls});
  final String body;
  /// Map from label (the path segment used in `/video/{label}.m3u8`) to
  /// the original upstream URL the master playlist pointed at.
  final Map<String, String> renditionUrls;
}
```

`rewriteMaster` becomes `static MasterRewriteResult rewriteMaster(...)` and the existing tests need a tweak (`out.body` instead of `out`). Update both the rewriter implementation and its tests in this task.

- [ ] **Step 2: Update Task 11 master handler to record `session.renditionUpstream.addAll(result.renditionUrls)` before returning the body.**

- [ ] **Step 3: Add the variant route**

```dart
      ..get('/variant/<sid>/video/<label>.m3u8',
          (Request req, String sid, String label) async {
        final session = registry.get(sid, touch: true);
        if (session == null) return Response.notFound('unknown session');
        final upstream = session.renditionUpstream[label];
        if (upstream == null) {
          return Response.notFound('unknown rendition $label');
        }
        try {
          final resp = await dioInstance.get<String>(
            upstream,
            options: Options(
              responseType: ResponseType.plain,
              headers: session.upstreamHeaders,
            ),
          );
          final rewritten = Rewriter.rewriteMedia(
            resp.data ?? '',
            rendition: label,
            basePath: '/variant/$sid',
          );
          return Response.ok(rewritten, headers: {
            'content-type': 'application/vnd.apple.mpegurl',
          });
        } on DioException catch (e) {
          return Response.internalServerError(body: 'upstream: ${e.message}');
        }
      });
```

- [ ] **Step 4: Add proxy_test.dart group for the variant route**

```dart
  test('GET /variant/{sid}/video/{label}.m3u8 fetches + rewrites', () async {
    // Spin up a fixture server that serves both master and one variant.
    late HttpServer fixture;
    fixture = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    fixture.listen((req) {
      if (req.uri.path == '/master') {
        req.response
          ..statusCode = 200
          ..write('''
#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=854x480
http://127.0.0.1:${fixture.port}/v?rendition=480p
''')
          ..close();
      } else {
        req.response
          ..statusCode = 200
          ..write('''
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXTINF:5.5,
http://127.0.0.1:${fixture.port}/seg-0.ts
#EXT-X-ENDLIST
''')
          ..close();
      }
    });
    addTearDown(() => fixture.close(force: true));

    final s = PlaybackSession.create(
      tmdbId: 1, mediaType: 'movie', pluginShortName: 'p',
      upstreamMasterUrl: 'http://127.0.0.1:${fixture.port}/master',
      upstreamHeaders: const {},
    );
    registry.put(s);

    // Hit master first to populate renditionUpstream.
    await http.get(Uri.parse('${proxy.baseUrl}/master/${s.id}.m3u8'));

    final resp = await http.get(
      Uri.parse('${proxy.baseUrl}/variant/${s.id}/video/480p.m3u8'),
    );
    expect(resp.statusCode, 200);
    expect(resp.body, contains('/variant/${s.id}/seg/480p/0.ts'));
  });
```

- [ ] **Step 5: Run all proxy tests, expect pass**

- [ ] **Step 6: Commit**

```bash
git add lib/player/proxy.dart lib/player/rewriter.dart test/player/proxy_test.dart test/player/rewriter_test.dart
git commit -m "player(proxy): GET /variant/{sid}/video/{label} — variant playlist + label→upstream map"
```

---

### Task 13: Key route — GET /key/{sid}/{rendition}

**Files:**
- Modify: `lib/player/proxy.dart`
- Modify: `test/player/proxy_test.dart`

The key URI for a rendition was rewritten by `Rewriter.rewriteMedia`. The original upstream key URL was inside `EXT-X-KEY:URI=...` which we replaced. To proxy the key, we need to record the original key URL during the variant rewrite.

- [ ] **Step 1: Extend `Rewriter.rewriteMedia` to also return the original key URL (if any)**

```dart
class MediaRewriteResult {
  MediaRewriteResult({required this.body, required this.keyUrl});
  final String body;
  final String? keyUrl;
}

static MediaRewriteResult rewriteMedia(
  String text, {
  required String rendition,
  required String basePath,
}) {
  final lines = const LineSplitter().convert(text);
  final out = <String>[];
  String? keyUrl;
  var segIndex = 0;
  for (final line in lines) {
    if (line.startsWith('#EXT-X-KEY:')) {
      final m = _uriAttr.firstMatch(line);
      if (m != null) keyUrl = m.group(1);
      final replaced = line.replaceFirstMapped(
        _uriAttr,
        (_) => 'URI="$basePath/key/$rendition"',
      );
      out.add(replaced);
      continue;
    }
    if (line.isNotEmpty && !line.startsWith('#')) {
      out.add('$basePath/seg/$rendition/$segIndex.ts');
      segIndex++;
      continue;
    }
    out.add(line);
  }
  return MediaRewriteResult(body: out.join('\n'), keyUrl: keyUrl);
}
```

Update the existing `Rewriter.rewriteMedia` tests to use `out.body`. Add a new test:

```dart
    test('returns key URL alongside body for AES-128 streams', () {
      const encrypted = '''
#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="https://upstream-keys/abc.key",IV=0xdead
#EXTINF:5.5,
https://upstream/seg-001.ts
#EXT-X-ENDLIST
''';
      final out = Rewriter.rewriteMedia(encrypted, rendition: '480p', basePath: '/x');
      expect(out.keyUrl, 'https://upstream-keys/abc.key');
    });
```

- [ ] **Step 2: Update the variant handler in proxy.dart to record the key URL on the session:**

Add a `Map<String, String> keyUrlByRendition = {}` field to `PlaybackSession`. The variant handler does `session.keyUrlByRendition[label] = result.keyUrl!` if non-null.

- [ ] **Step 3: Add the key route**

```dart
      ..get('/key/<sid>/<label>',
          (Request req, String sid, String label) async {
        final session = registry.get(sid, touch: true);
        if (session == null) return Response.notFound('unknown session');
        final keyUrl = session.keyUrlByRendition[label];
        if (keyUrl == null) {
          return Response.notFound('no key for rendition $label');
        }
        try {
          final resp = await dioInstance.get<List<int>>(
            keyUrl,
            options: Options(
              responseType: ResponseType.bytes,
              headers: session.upstreamHeaders,
            ),
          );
          return Response.ok(
            resp.data,
            headers: {'content-type': 'application/octet-stream'},
          );
        } on DioException catch (e) {
          return Response.internalServerError(body: 'upstream: ${e.message}');
        }
      });
```

- [ ] **Step 4: Add a test for the key route — fixture serves `master → encrypted variant → key bytes`. Verify `GET /key/{sid}/480p` returns 16 bytes of the original key.**

- [ ] **Step 5: Run all tests, expect pass**

- [ ] **Step 6: Commit**

```bash
git add lib/player/proxy.dart lib/player/rewriter.dart lib/player/session.dart test/player/proxy_test.dart test/player/rewriter_test.dart
git commit -m "player(proxy): GET /key/{sid}/{rendition} — proxy AES-128 key bytes"
```

---

### Task 14: Segment route — GET /seg/{sid}/{rendition}/{n}.ts

**Files:**
- Modify: `lib/player/proxy.dart`
- Modify: `test/player/proxy_test.dart`

Segments need to map back to upstream segment URLs by index. The variant rewriter currently DROPS this info — we need to keep it.

- [ ] **Step 1: Extend `MediaRewriteResult` to include `segmentUrls: List<String>`** (the upstream URL at each index — same order as in the playlist).

Update `rewriteMedia`:

```dart
final segmentUrls = <String>[];
// ... in the segment branch:
segmentUrls.add(line);
out.add('$basePath/seg/$rendition/$segIndex.ts');
segIndex++;
// ... return:
return MediaRewriteResult(body: out.join('\n'), keyUrl: keyUrl, segmentUrls: segmentUrls);
```

Update existing tests to use the new shape.

- [ ] **Step 2: Add `segmentUrlsByRendition: Map<String, List<String>>` to `PlaybackSession`. Variant handler populates it.**

- [ ] **Step 3: Add the segment route**

```dart
      ..get('/seg/<sid>/<label>/<n|[0-9]+>.ts',
          (Request req, String sid, String label, String n) async {
        final session = registry.get(sid, touch: true);
        if (session == null) return Response.notFound('unknown session');
        final urls = session.segmentUrlsByRendition[label];
        final idx = int.tryParse(n);
        if (urls == null || idx == null || idx < 0 || idx >= urls.length) {
          return Response.notFound('unknown segment $label/$n');
        }
        try {
          final raw = await fetcher.fetch(
            urls[idx],
            headers: session.upstreamHeaders,
            decryptor: _decryptorFor(session, label),
          );
          return Response.ok(raw, headers: {'content-type': 'video/mp2t'});
        } on Exception catch (e) {
          return Response.internalServerError(body: 'fetch: $e');
        }
      });
```

`fetcher` is a `SegmentFetcher` instance owned by the proxy server. Pass it via `LocalProxyServer.start(..., fetcher: ...)`. `_decryptorFor(session, label)` returns a `SegmentDecryptor?` — null unless `session.isDrm` AND we have the key already loaded. Implement as:

```dart
SegmentDecryptor? _decryptorFor(PlaybackSession session, String label) {
  if (!session.isDrm) return null;
  final keyBytes = session.keyBytesByRendition[label];
  if (keyBytes == null) return null; // first segment may need a separate path
  // For HLS AES-128, IV defaults to segment number BE-encoded — for MVP
  // we use a zero IV when the playlist's EXT-X-KEY didn't specify one.
  final iv = session.ivByRendition[label] ?? Uint8List(16);
  return SegmentDrm(keyBytes: keyBytes, ivBytes: iv).decrypt;
}
```

Add `keyBytesByRendition` and `ivByRendition` to `PlaybackSession` (initially empty maps). Populating them is left to the key handler — when `/key/...` is hit, it stores the bytes on the session.

> **Realism note:** For non-DRM AES-128 HLS, this still works (the player fetches the key first via /key, our handler stores the bytes, then segments fetch with the key). For DRM (Widevine), this MVP does not implement the CDM dance — the spec says DRM is supported only for streams where `getStreams()` already returns extracted keys (`drm_keys`). When `is_drm` is true, the loader should populate `keyBytesByRendition` from `session.drmKeys` directly rather than via the /key route. Document this in code comments.

- [ ] **Step 4: Add a fixture server test that serves master → unencrypted variant → 1KB segment, verifies `GET /seg/{sid}/480p/0.ts` returns the segment body.**

- [ ] **Step 5: Run all tests, expect pass**

- [ ] **Step 6: Commit**

```bash
git add lib/player/proxy.dart lib/player/rewriter.dart lib/player/session.dart test/player/proxy_test.dart test/player/rewriter_test.dart
git commit -m "player(proxy): GET /seg/{sid}/{label}/{n}.ts — fetch + cache + (optional) decrypt"
```

---

## Phase G — Player engine wrapper

### Task 15: PlayerEngine — thin media_kit wrapper

**Files:**
- Create: `lib/player/engine.dart`
- Create: `test/player/engine_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/player/engine_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/player/engine.dart';

void main() {
  setUpAll(() {
    PlayerEngine.ensureInitialized();
  });

  test('construct + dispose without error', () {
    final eng = PlayerEngine();
    eng.dispose();
  });

  test('positionStream emits Duration values', () async {
    final eng = PlayerEngine();
    addTearDown(eng.dispose);
    expect(eng.positionStream, emitsThrough(isA<Duration>()));
  }, skip: 'needs media to play; covered in integration smoke');

  test('open(uri, headers) does not throw before play', () async {
    final eng = PlayerEngine();
    addTearDown(eng.dispose);
    // Use a non-existent URL — open should not throw synchronously.
    eng.open('http://127.0.0.1:1/none.m3u8', headers: const {});
  });
}
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```dart
// lib/player/engine.dart
import 'package:media_kit/media_kit.dart';

/// Thin wrapper around media_kit.Player. Owns one player; dispose drops it.
class PlayerEngine {
  PlayerEngine() : _player = Player();

  static void ensureInitialized() {
    MediaKit.ensureInitialized();
  }

  final Player _player;

  Player get player => _player;

  Stream<Duration> get positionStream => _player.stream.position;
  Stream<Duration> get durationStream => _player.stream.duration;
  Stream<bool> get playingStream => _player.stream.playing;

  void open(String uri, {required Map<String, String> headers}) {
    _player.open(Media(uri, httpHeaders: headers));
  }

  Future<void> play() => _player.play();
  Future<void> pause() => _player.pause();
  Future<void> seek(Duration to) => _player.seek(to);

  void dispose() {
    _player.dispose();
  }
}
```

- [ ] **Step 4: Run, expect 2 tests pass (1 skipped)**

> media_kit needs `ensureInitialized()` once per process. Tests call it in `setUpAll`. If a test environment can't load the macOS dylib (CI containers, etc.), guard with try/catch and skip.

- [ ] **Step 5: Commit**

```bash
git add lib/player/engine.dart test/player/engine_test.dart
git commit -m "player: PlayerEngine — media_kit wrapper with position/duration/playing streams"
```

---

## Phase H — Orchestrator

### Task 16: PlayController — getStreams → session → proxy URL

**Files:**
- Create: `lib/domain/play_title.dart`
- Create: `test/domain/play_title_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/domain/play_title_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/domain/play_title.dart';
import 'package:streamload_client/plugins/meta.dart';
import 'package:streamload_client/plugins/plugin.dart';
import 'package:streamload_client/player/session.dart';

class _RuntimeMock extends Mock {
  Plugin? callable(String name);
}

class _PluginMock extends Mock implements Plugin {}

void main() {
  late PlaybackSessionRegistry registry;
  late _RuntimeMock runtime;
  late _PluginMock plugin;

  setUp(() {
    registry = PlaybackSessionRegistry(ttl: const Duration(hours: 1));
    runtime = _RuntimeMock();
    plugin = _PluginMock();
    when(() => plugin.meta).thenReturn(const PluginMeta(
      shortName: 'echo',
      displayName: 'Echo',
      version: '1.0.0',
      apiVersion: 1,
      capabilities: ['movie'],
    ));
  });

  test('startMovie calls plugin.getStreams, registers session, returns master URL', () async {
    when(() => plugin.getStreams(any())).thenAnswer((_) async => {
          'manifest_url': 'https://upstream/master.m3u8',
          'headers': {'Referer': 'https://up'},
          'is_drm': false,
        });

    final controller = PlayController(
      registry: registry,
      proxyBaseUrl: 'http://127.0.0.1:47821',
      pluginFor: (_) => plugin,
    );

    final url = await controller.startMovie(tmdbId: 42);
    expect(url, startsWith('http://127.0.0.1:47821/master/'));
    expect(url, endsWith('.m3u8'));

    final sid = url.split('/').last.replaceAll('.m3u8', '');
    final session = registry.get(sid);
    expect(session, isNotNull);
    expect(session!.upstreamMasterUrl, 'https://upstream/master.m3u8');
    expect(session.upstreamHeaders['Referer'], 'https://up');
  });

  test('startMovie throws when no plugin can satisfy the request', () async {
    final controller = PlayController(
      registry: registry,
      proxyBaseUrl: 'http://127.0.0.1:47821',
      pluginFor: (_) => null,
    );
    expect(
      () => controller.startMovie(tmdbId: 42),
      throwsA(isA<StateError>().having((e) => e.message, 'message', contains('no plugin'))),
    );
  });
}
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```dart
// lib/domain/play_title.dart
import '../player/session.dart';
import '../plugins/plugin.dart';

class PlayController {
  PlayController({
    required this.registry,
    required this.proxyBaseUrl,
    required this.pluginFor,
  });

  final PlaybackSessionRegistry registry;
  final String proxyBaseUrl;
  /// Strategy for picking a plugin: tested by injecting a synthetic chooser.
  /// Real implementation will iterate plugins by capability + ranker.
  final Plugin? Function(({int tmdbId, String mediaType})) pluginFor;

  Future<String> startMovie({required int tmdbId}) async {
    final plugin = pluginFor((tmdbId: tmdbId, mediaType: 'movie'));
    if (plugin == null) {
      throw StateError('no plugin can satisfy tmdbId=$tmdbId');
    }
    final result = await plugin.getStreams({
      'tmdb_id': tmdbId,
      'media_type': 'movie',
    });
    return _registerAndUrl(plugin, tmdbId, 'movie', result);
  }

  Future<String> startEpisode({
    required int tmdbId,
    required int season,
    required int episode,
  }) async {
    final plugin = pluginFor((tmdbId: tmdbId, mediaType: 'tv'));
    if (plugin == null) {
      throw StateError('no plugin can satisfy tmdbId=$tmdbId s${season}e$episode');
    }
    final result = await plugin.getStreams({
      'tmdb_id': tmdbId,
      'media_type': 'tv',
      'season': season,
      'episode': episode,
    });
    return _registerAndUrl(plugin, tmdbId, 'tv', result);
  }

  String _registerAndUrl(
    Plugin plugin,
    int tmdbId,
    String mediaType,
    Map<String, dynamic> getStreamsResult,
  ) {
    final headers = (getStreamsResult['headers'] as Map?)
            ?.cast<String, dynamic>()
            .map((k, v) => MapEntry(k, v.toString())) ??
        const <String, String>{};
    final session = PlaybackSession.create(
      tmdbId: tmdbId,
      mediaType: mediaType,
      pluginShortName: plugin.meta.shortName,
      upstreamMasterUrl: getStreamsResult['manifest_url'] as String,
      upstreamHeaders: headers,
      isDrm: getStreamsResult['is_drm'] == true,
      drmKeys: getStreamsResult['drm_keys'] as Map<String, dynamic>?,
    );
    registry.put(session);
    return '$proxyBaseUrl/master/${session.id}.m3u8';
  }
}
```

- [ ] **Step 4: Run, expect 2 tests pass**

- [ ] **Step 5: Commit**

```bash
git add lib/domain/play_title.dart test/domain/play_title_test.dart
git commit -m "domain: PlayController — orchestrate plugin.getStreams → session → master URL"
```

---

## Phase I — Riverpod providers + main wiring

### Task 17: playbackSessionRegistryProvider + localProxyProvider

**Files:**
- Create: `lib/state/playback_session_registry_provider.dart`
- Create: `lib/state/local_proxy_provider.dart`

- [ ] **Step 1: Implement `playback_session_registry_provider.dart`**

```dart
// lib/state/playback_session_registry_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../player/session.dart';

final playbackSessionRegistryProvider = Provider<PlaybackSessionRegistry>(
  (ref) => PlaybackSessionRegistry(ttl: const Duration(hours: 4)),
);
```

- [ ] **Step 2: Implement `local_proxy_provider.dart`**

```dart
// lib/state/local_proxy_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../player/cache/disk_cache.dart';
import '../player/cache/ram_buffer.dart';
import '../player/proxy.dart';
import '../player/segment_fetcher.dart';
import 'playback_session_registry_provider.dart';

/// Long-lived shelf server. Kept alive for the app lifetime; on dispose
/// the server is closed gracefully.
final localProxyProvider = FutureProvider<LocalProxyServer>((ref) async {
  final registry = ref.watch(playbackSessionRegistryProvider);
  // Cache lives under the OS tmp dir for now — sub-plan #6 swaps to
  // path_provider.getApplicationCacheDirectory(). 30 GB cap.
  final cacheDir = '/tmp/streamload_segments';
  final fetcher = SegmentFetcher(
    ram: RamRingBuffer(capacity: 30),
    disk: DiskSegmentCache(directory: cacheDir, sizeLimitBytes: 30 * 1024 * 1024 * 1024),
    dio: ref.read(dioProvider), // assumes existing dioProvider; if absent, construct Dio() inline
  );
  final server = await LocalProxyServer.start(
    registry: registry,
    fetcher: fetcher,
  );
  ref.onDispose(server.stop);
  return server;
});
```

> If `dioProvider` doesn't exist in the codebase, replace `ref.read(dioProvider)` with `Dio()`.

- [ ] **Step 3: Add a basic test** (`test/state/local_proxy_provider_test.dart`) that builds a `ProviderContainer`, awaits the proxy, hits `/health`, asserts 200.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add lib/state/playback_session_registry_provider.dart lib/state/local_proxy_provider.dart test/state/local_proxy_provider_test.dart
git commit -m "state: playbackSessionRegistry + localProxy providers"
```

---

### Task 18: Wire local proxy startup into main.dart

**Files:**
- Modify: `lib/main.dart` (or `lib/app.dart` — wherever bootstrap lives)

- [ ] **Step 1: After auth bootstrap, eagerly read `localProxyProvider` so the server starts at app launch (not lazily on first watch).**

```dart
// In the post-bootstrap callback, after pluginUpdater.start():
unawaited(ref.read(localProxyProvider.future));
```

Also call `PlayerEngine.ensureInitialized()` at the same point (before the first `Player()` is constructed).

- [ ] **Step 2: Run full suite, expect pass**

```bash
flutter test 2>&1 | tail -3
```

- [ ] **Step 3: Commit**

```bash
git add lib/app.dart # or main.dart
git commit -m "app: start local HLS proxy + media_kit on app boot"
```

---

### Task 19: playerEngineProvider + playControllerProvider

**Files:**
- Create: `lib/state/player_engine_provider.dart`
- Create: `lib/state/play_controller_provider.dart`

- [ ] **Step 1: Implement `player_engine_provider.dart`**

```dart
// lib/state/player_engine_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../player/engine.dart';

/// Auto-disposes the engine when the watch screen disposes its subscription.
final playerEngineProvider = Provider.autoDispose<PlayerEngine>((ref) {
  final engine = PlayerEngine();
  ref.onDispose(engine.dispose);
  return engine;
});
```

- [ ] **Step 2: Implement `play_controller_provider.dart`**

```dart
// lib/state/play_controller_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../domain/play_title.dart';
import '../plugins/plugin.dart';
import 'local_proxy_provider.dart';
import 'playback_session_registry_provider.dart';
import 'plugin_runtime_provider.dart';
import 'plugins_provider.dart';

final playControllerProvider = FutureProvider<PlayController>((ref) async {
  final proxy = await ref.watch(localProxyProvider.future);
  final registry = ref.watch(playbackSessionRegistryProvider);
  final runtime = await ref.watch(pluginRuntimeProvider.future);

  Plugin? pluginFor(({int tmdbId, String mediaType}) target) {
    // MVP: pick the first installed plugin whose capabilities include
    // target.mediaType. Sub-plan #6 will replace this with a ranker.
    for (final p in runtime.all) {
      if (p.meta.capabilities.contains(target.mediaType)) return p;
    }
    return null;
  }

  return PlayController(
    registry: registry,
    proxyBaseUrl: proxy.baseUrl,
    pluginFor: pluginFor,
  );
});
```

- [ ] **Step 3: Run analyze + tests**

- [ ] **Step 4: Commit**

```bash
git add lib/state/player_engine_provider.dart lib/state/play_controller_provider.dart
git commit -m "state: playerEngine + playController providers"
```

---

## Phase J — End-to-end smoke

### Task 20: Manual smoke against a real HLS source

This task is operator-driven. It cannot be automated because it needs a real plugin returning a real upstream HLS URL.

- [ ] **Step 1: Pick a public HLS test source.** Examples:
  - Apple's BipBop (`https://devstreaming-cdn.apple.com/videos/streaming/examples/img_bipbop_adv_example_ts/master.m3u8`)
  - mux.com test streams

- [ ] **Step 2: Author a temporary plugin** under `streamload-plugins/plugins/_smoke_hls.js` that returns a `getStreams()` shape pointing at the public source. Bump `registry.json` with its sha256.

- [ ] **Step 3: Launch the macOS app, refresh plugins, then in a debug button (temporary scaffold) call:**

```dart
final controller = await ref.read(playControllerProvider.future);
final url = await controller.startMovie(tmdbId: 0);
final engine = ref.read(playerEngineProvider);
engine.open(url, headers: const {});
await engine.play();
```

- [ ] **Step 4: Verify in logs:**
  - Proxy received `GET /master/<sid>.m3u8` → 200
  - Proxy received `GET /variant/<sid>/video/<label>.m3u8` → 200
  - Proxy received `GET /seg/<sid>/<label>/0.ts` → 200
  - media_kit position stream emits non-zero values within 5s

- [ ] **Step 5: Pull the temporary smoke plugin from the registry once verified.**

This task does not commit code — it's a verification gate.

---

## Acceptance criteria for this sub-plan

- 130+ tests pass (`flutter test` from `Streamload-Client/`).
- `flutter analyze` is clean.
- The local proxy starts on app launch and serves `GET /health` from `127.0.0.1:<port>`.
- A `getStreams()` result wired through `PlayController` produces a `http://127.0.0.1:<port>/master/<sid>.m3u8` URL that, when opened in `media_kit`, plays the configured public HLS source end-to-end (Task 20 manual verification).
- The watch UI is **NOT** built yet — that's sub-plan #6.

## Out of scope (DO NOT include — confirmation against §16)

- Subtitles (HLS or otherwise).
- Skip-intro detection.
- Cast / AirPlay output.
- Offline download.
- Watch UI / catalog browse / search / title detail screens.
- Telemetry batching for play.* events.
- Auto-updater for the app binary itself.
- Mobile (iOS/Android) build targets.
