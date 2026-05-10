# v3 Plugin Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring up a QuickJS sandbox inside the Flutter client that can fetch the private `streamload-plugins` registry with a per-user GitHub PAT, sha256-verify each plugin, mount it in JS, and call its async functions from Dart through a strictly-scoped `host.*` bridge.

**Architecture:** `flutter_js` (QuickJS-NG) hosts an isolated JavaScript runtime. Plugins are vanilla ESM `.js` files; we strip the `export` prefix and wrap each one in an IIFE that returns its public API into a per-plugin slot under `globalThis.__sl_plugins[short_name]`. JS calls into Dart via a single `host_call` channel that demultiplexes by `(module, method)` and dispatches to typed Dart handlers (http, html, crypto, log, storage, url, json). A loader walks the GitHub-served `registry.json`, downloads only changed entries, verifies sha256, and atomically swaps each plugin into the runtime.

**Tech Stack:** Flutter 3.41+, Dart 3.11+, flutter_js 0.8 (QuickJS-NG), html 0.15, pointycastle 3.9, crypto 3.0, riverpod 2.5, drift 2.18, freezed 2.5.

---

## Source spec

This plan implements **Sub-plan #4** from `docs/superpowers/specs/2026-05-09-streamload-v3-design.md` §17. The plugin contract it consumes is the one defined in `streamload-plugins/docs/plugin-contract.md` (Plan #2). Schema tables `installed_plugins` and `plugin_kv` were created in Plan #3 (drift v1) and are populated for the first time by this plan.

The terminal state of this plan is: launching the app for the first time after Plan #3 → log in → wizard step asks for a GitHub PAT → paste a real fine-grained token scoped to `alfanowski/streamload-plugins` → app fetches `registry.json`, downloads `plugins/_fixture/echo.js`, mounts it in QuickJS → `Plugin('echo').search('hello')` returns the deterministic synthetic shape from Plan #2's fixture.

## File structure

### New files (Tasks 1-25)

| Path | Created in | Purpose |
|---|---|---|
| `lib/plugins/host/log_host.dart` | T4 | host.log.* → Logger funnel |
| `lib/plugins/host/json_host.dart` | T5 | host.json.parse/stringify |
| `lib/plugins/host/url_host.dart` | T6 | host.url.absolute |
| `lib/plugins/host/crypto_host.dart` | T7 | host.crypto.* (sha256, md5, hmac, base64, aesDecrypt) |
| `lib/plugins/host/http_host.dart` | T8 | host.http.fetch wrapping dio (10s timeout, 10MB cap, 5 redirects) |
| `lib/plugins/host/html_host.dart` | T9 | host.html.parse cheerio-shaped wrapper around package:html |
| `lib/plugins/host/storage_host.dart` | T10 | host.storage.* backed by PluginKvDao, namespaced per plugin |
| `lib/plugins/meta.dart` | T11 | freezed `PluginMeta` + validation |
| `lib/plugins/plugin.dart` | T12 | typed `Plugin.search/getSeasons/getEpisodes/getStreams` Dart wrapper |
| `lib/plugins/runtime.dart` | T13-T14 | `PluginRuntime` — owns the JsRuntime + mount/unmount + host bridge |
| `lib/plugins/host_api.dart` | T13 | central `host_call` channel dispatcher |
| `lib/plugins/github_client.dart` | T15 | dio-backed GitHub raw + contents API helper, uses PAT |
| `lib/plugins/registry.dart` | T16 | diff between in-DB installed plugins and remote registry |
| `lib/plugins/loader.dart` | T17 | orchestrates registry → diff → fetch → sha256 → mount/swap |
| `lib/plugins/updater.dart` | T24 | periodic refresh loop (every 30 min while app open) |
| `lib/data/local/daos/installed_plugins_dao.dart` | T2 | drift DAO for InstalledPlugins |
| `lib/data/local/daos/plugin_kv_dao.dart` | T3 | drift DAO for PluginKv |
| `lib/state/github_pat_provider.dart` | T18 | reactive PAT (read/write through SecureStorage) |
| `lib/state/plugin_runtime_provider.dart` | T19 | singleton PluginRuntime (long-lived) |
| `lib/state/plugins_provider.dart` | T20 | installed-plugins stream + refresh/enable/remove mutators |
| `lib/presentation/pages/plugin_onboarding_page.dart` | T21 | first-run wizard step 3 (PAT paste) |
| `lib/presentation/pages/plugins_page.dart` | T23 | settings sub-page: installed plugins list + actions |
| `test/plugins/host/log_host_test.dart` | T4 | log routing |
| `test/plugins/host/json_host_test.dart` | T5 | parse + stringify |
| `test/plugins/host/url_host_test.dart` | T6 | absolute URL resolution |
| `test/plugins/host/crypto_host_test.dart` | T7 | known-vector sha256/md5/hmac/aes |
| `test/plugins/host/http_host_test.dart` | T8 | dio mock + timeout + size cap |
| `test/plugins/host/html_host_test.dart` | T9 | parse + querySelector + attr/text |
| `test/plugins/host/storage_host_test.dart` | T10 | namespaced get/set/delete via in-memory drift |
| `test/plugins/meta_test.dart` | T11 | accepted + rejected meta payloads |
| `test/plugins/registry_test.dart` | T16 | diff cases (new, changed, removed, unchanged) |
| `test/plugins/loader_test.dart` | T17 | end-to-end with mocked GitHub responses + the echo fixture body |
| `test/plugins/runtime_test.dart` | T14 | mount + call + atomic-swap (sha256 mismatch keeps prev) |
| `test/data/installed_plugins_dao_test.dart` | T2 | round-trip |
| `test/data/plugin_kv_dao_test.dart` | T3 | round-trip + namespace isolation |
| `test/pages/plugin_onboarding_page_test.dart` | T21 | paste-PAT flow with mocked GitHub |

### Modified files

| Path | Modified in | Change |
|---|---|---|
| `pubspec.yaml` | T1 | add `flutter_js`, `html`, `pointycastle`, `crypto` |
| `lib/data/local/database.dart` | T2-T3 | add the 2 new DAOs to `daos:` list |
| `lib/router.dart` | T22 | when authenticated AND no PAT in keychain → redirect to `/onboarding/plugins` |
| `lib/presentation/pages/settings_page.dart` | T23 | add "Plugin" link → `/plugins` page |
| `lib/main.dart` | T24 | start the updater poll loop after auth bootstrap |

---

## Phase A — Dependencies + DAOs

### Task 1: Add `flutter_js`, `html`, `pointycastle`, `crypto` to pubspec.yaml

**Files:**
- Modify: `pubspec.yaml`

- [ ] **Step 1: Edit `pubspec.yaml` — add the four deps under the existing `dependencies:` block**

Find the `dependencies:` section (around line 11 of the existing `pubspec.yaml`). After `lucide_icons:`, add:

```yaml
  # Plugin runtime
  flutter_js: ^0.8.1
  html: ^0.15.5
  pointycastle: ^3.9.1
  crypto: ^3.0.5
```

- [ ] **Step 2: Resolve**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
flutter pub get
```

Expected: `Got dependencies!` with no resolution conflicts.

- [ ] **Step 3: Sanity check that flutter_js loads**

```bash
flutter test --plain-name "no plugin" 2>&1 | tail -3
```

Expected: existing 38 tests still pass (no new tests yet).

- [ ] **Step 4: Commit**

```bash
git add pubspec.yaml pubspec.lock
git commit -m "deps: flutter_js + html + pointycastle + crypto for plugin runtime"
```

---

### Task 2: `installed_plugins_dao.dart` + DB registration + tests

**Files:**
- Create: `lib/data/local/daos/installed_plugins_dao.dart`
- Modify: `lib/data/local/database.dart`
- Create: `test/data/installed_plugins_dao_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/data/installed_plugins_dao_test.dart
import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/data/local/database.dart';
import 'package:streamload_client/data/local/schema/installed_plugins.dart';

void main() {
  late StreamloadDatabase db;

  setUp(() {
    db = StreamloadDatabase.test(NativeDatabase.memory());
  });

  tearDown(() => db.close());

  test('upsert + listAll round-trip', () async {
    await db.installedPluginsDao.upsert(InstalledPluginsCompanion.insert(
      shortName: 'echo',
      version: '1.0.0',
      sha256: 'aa' * 32,
      filePath: '/cache/plugins/echo.js',
    ));
    final rows = await db.installedPluginsDao.listAll();
    expect(rows, hasLength(1));
    expect(rows.first.shortName, 'echo');
    expect(rows.first.enabled, isTrue);
  });

  test('upsert overwrites existing row by short_name PK', () async {
    await db.installedPluginsDao.upsert(InstalledPluginsCompanion.insert(
      shortName: 'echo', version: '1.0.0',
      sha256: 'aa' * 32, filePath: '/x',
    ));
    await db.installedPluginsDao.upsert(InstalledPluginsCompanion.insert(
      shortName: 'echo', version: '1.0.1',
      sha256: 'bb' * 32, filePath: '/y',
    ));
    final row = (await db.installedPluginsDao.listAll()).single;
    expect(row.version, '1.0.1');
    expect(row.sha256, 'bb' * 32);
    expect(row.filePath, '/y');
  });

  test('setEnabled flips the flag', () async {
    await db.installedPluginsDao.upsert(InstalledPluginsCompanion.insert(
      shortName: 'echo', version: '1.0.0',
      sha256: 'aa' * 32, filePath: '/x',
    ));
    await db.installedPluginsDao.setEnabled('echo', false);
    final row = (await db.installedPluginsDao.listAll()).single;
    expect(row.enabled, isFalse);
  });

  test('delete drops the row', () async {
    await db.installedPluginsDao.upsert(InstalledPluginsCompanion.insert(
      shortName: 'echo', version: '1.0.0',
      sha256: 'aa' * 32, filePath: '/x',
    ));
    await db.installedPluginsDao.delete('echo');
    expect(await db.installedPluginsDao.listAll(), isEmpty);
  });
}
```

- [ ] **Step 2: Run, expect failure (DAO doesn't exist yet)**

```bash
flutter test test/data/installed_plugins_dao_test.dart
```

Expected: import error or `db.installedPluginsDao` undefined.

- [ ] **Step 3: Write the DAO**

```dart
// lib/data/local/daos/installed_plugins_dao.dart
import 'package:drift/drift.dart';

import '../database.dart';
import '../schema/installed_plugins.dart';

part 'installed_plugins_dao.g.dart';

@DriftAccessor(tables: [InstalledPlugins])
class InstalledPluginsDao extends DatabaseAccessor<StreamloadDatabase>
    with _$InstalledPluginsDaoMixin {
  InstalledPluginsDao(super.db);

  Future<List<InstalledPluginRow>> listAll() {
    return select(installedPlugins).get();
  }

  Stream<List<InstalledPluginRow>> watchAll() {
    return select(installedPlugins).watch();
  }

  Future<InstalledPluginRow?> getByName(String shortName) {
    return (select(installedPlugins)
          ..where((t) => t.shortName.equals(shortName)))
        .getSingleOrNull();
  }

  Future<void> upsert(InstalledPluginsCompanion entry) async {
    await into(installedPlugins).insertOnConflictUpdate(entry);
  }

  Future<void> setEnabled(String shortName, bool enabled) async {
    await (update(installedPlugins)
          ..where((t) => t.shortName.equals(shortName)))
        .write(InstalledPluginsCompanion(enabled: Value(enabled)));
  }

  Future<void> delete(String shortName) async {
    await (this.delete(installedPlugins)
          ..where((t) => t.shortName.equals(shortName)))
        .go();
  }
}
```

- [ ] **Step 4: Register the DAO in `lib/data/local/database.dart`**

Add to imports near the other DAO imports:

```dart
import 'daos/installed_plugins_dao.dart';
```

In the `@DriftDatabase(...)` annotation, add `InstalledPluginsDao` to the `daos:` list:

```dart
@DriftDatabase(tables: [
  CatalogItems,
  TvEpisodes,
  CatalogSources,
  WatchProgress,
  Favorites,
  Watchlist,
  UserSettings,
  Outbox,
  InstalledPlugins,
  PluginKv,
], daos: [
  CatalogDao,
  UserSettingsDao,
  InstalledPluginsDao,
])
```

- [ ] **Step 5: Run code-gen**

```bash
dart run build_runner build --delete-conflicting-outputs
```

Expected: regenerates `database.g.dart` + creates `installed_plugins_dao.g.dart`.

- [ ] **Step 6: Run tests, expect pass**

```bash
flutter test test/data/installed_plugins_dao_test.dart
```

Expected: 4 tests pass.

- [ ] **Step 7: Commit**

```bash
git add lib/data/local/daos/installed_plugins_dao.dart lib/data/local/database.dart lib/data/local/database.g.dart lib/data/local/daos/installed_plugins_dao.g.dart test/data/installed_plugins_dao_test.dart
git commit -m "data: InstalledPluginsDao + 4 round-trip tests"
```

---

### Task 3: `plugin_kv_dao.dart` + DB registration + tests

**Files:**
- Create: `lib/data/local/daos/plugin_kv_dao.dart`
- Modify: `lib/data/local/database.dart`
- Create: `test/data/plugin_kv_dao_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/data/plugin_kv_dao_test.dart
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/data/local/database.dart';

void main() {
  late StreamloadDatabase db;

  setUp(() => db = StreamloadDatabase.test(NativeDatabase.memory()));
  tearDown(() => db.close());

  test('set + get round-trip per (plugin, key)', () async {
    await db.pluginKvDao.set('echo', 'token', 'abc');
    expect(await db.pluginKvDao.get('echo', 'token'), 'abc');
    expect(await db.pluginKvDao.get('echo', 'missing'), isNull);
  });

  test('set is overwrite-on-conflict', () async {
    await db.pluginKvDao.set('echo', 'token', 'v1');
    await db.pluginKvDao.set('echo', 'token', 'v2');
    expect(await db.pluginKvDao.get('echo', 'token'), 'v2');
  });

  test('delete removes the row', () async {
    await db.pluginKvDao.set('echo', 'token', 'abc');
    await db.pluginKvDao.delete('echo', 'token');
    expect(await db.pluginKvDao.get('echo', 'token'), isNull);
  });

  test('namespaces are isolated across plugins', () async {
    await db.pluginKvDao.set('echo', 'shared_key', 'echo_val');
    await db.pluginKvDao.set('sc', 'shared_key', 'sc_val');
    expect(await db.pluginKvDao.get('echo', 'shared_key'), 'echo_val');
    expect(await db.pluginKvDao.get('sc', 'shared_key'), 'sc_val');
  });

  test('clearForPlugin wipes only that plugin', () async {
    await db.pluginKvDao.set('echo', 'a', '1');
    await db.pluginKvDao.set('echo', 'b', '2');
    await db.pluginKvDao.set('sc', 'a', '3');
    await db.pluginKvDao.clearForPlugin('echo');
    expect(await db.pluginKvDao.get('echo', 'a'), isNull);
    expect(await db.pluginKvDao.get('echo', 'b'), isNull);
    expect(await db.pluginKvDao.get('sc', 'a'), '3');
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/data/plugin_kv_dao_test.dart
```

Expected: undefined `pluginKvDao`.

- [ ] **Step 3: Write the DAO**

```dart
// lib/data/local/daos/plugin_kv_dao.dart
import 'package:drift/drift.dart';

import '../database.dart';
import '../schema/plugin_kv.dart';

part 'plugin_kv_dao.g.dart';

@DriftAccessor(tables: [PluginKv])
class PluginKvDao extends DatabaseAccessor<StreamloadDatabase>
    with _$PluginKvDaoMixin {
  PluginKvDao(super.db);

  Future<String?> get(String pluginShortName, String key) async {
    final row = await (select(pluginKv)
          ..where((t) =>
              t.pluginShortName.equals(pluginShortName) & t.key.equals(key)))
        .getSingleOrNull();
    return row?.value;
  }

  Future<void> set(String pluginShortName, String key, String value) async {
    await into(pluginKv).insertOnConflictUpdate(PluginKvCompanion(
      pluginShortName: Value(pluginShortName),
      key: Value(key),
      value: Value(value),
    ));
  }

  Future<void> delete(String pluginShortName, String key) async {
    await (this.delete(pluginKv)
          ..where((t) =>
              t.pluginShortName.equals(pluginShortName) & t.key.equals(key)))
        .go();
  }

  Future<void> clearForPlugin(String pluginShortName) async {
    await (this.delete(pluginKv)
          ..where((t) => t.pluginShortName.equals(pluginShortName)))
        .go();
  }
}
```

- [ ] **Step 4: Register in `lib/data/local/database.dart`**

Add import:

```dart
import 'daos/plugin_kv_dao.dart';
```

Append to the `daos:` list:

```dart
], daos: [
  CatalogDao,
  UserSettingsDao,
  InstalledPluginsDao,
  PluginKvDao,
])
```

- [ ] **Step 5: Run code-gen + tests**

```bash
dart run build_runner build --delete-conflicting-outputs
flutter test test/data/plugin_kv_dao_test.dart
```

Expected: 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add lib/data/local/daos/plugin_kv_dao.dart lib/data/local/database.dart lib/data/local/*.g.dart test/data/plugin_kv_dao_test.dart
git commit -m "data: PluginKvDao with namespace isolation + 5 tests"
```

---

## Phase B — Host API surface (one task per host module)

### Task 4: `host.log` — funnel into Logger

**Files:**
- Create: `lib/plugins/host/log_host.dart`
- Create: `test/plugins/host/log_host_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/plugins/host/log_host_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/plugins/host/log_host.dart';

void main() {
  test('dispatch routes by level + tags with plugin name', () {
    final captured = <String>[];
    final host = LogHost(
      sink: (level, tag, msg) =>
          captured.add('${level.name}|$tag|$msg'),
    );

    host.handle('echo', 'debug', 'hello');
    host.handle('echo', 'info', 'started');
    host.handle('sc', 'warn', 'rate limit');
    host.handle('sc', 'error', 'boom');

    expect(captured, [
      'debug|plugin:echo|hello',
      'info|plugin:echo|started',
      'warn|plugin:sc|rate limit',
      'error|plugin:sc|boom',
    ]);
  });

  test('unknown level falls back to info', () {
    final captured = <String>[];
    final host = LogHost(
      sink: (level, tag, msg) => captured.add('${level.name}|$msg'),
    );
    host.handle('echo', 'made_up_level', 'hi');
    expect(captured.single, 'info|hi');
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/plugins/host/log_host_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/plugins/host/log_host.dart
import '../../infra/logger.dart';

typedef LogSink = void Function(LogLevel level, String tag, String message);

class LogHost {
  /// `sink` defaults to the project's Logger; tests can inject a capture sink.
  LogHost({LogSink? sink}) : _sink = sink ?? _defaultSink;

  final LogSink _sink;

  void handle(String pluginShortName, String level, String message) {
    final lvl = switch (level) {
      'debug' => LogLevel.debug,
      'info' => LogLevel.info,
      'warn' => LogLevel.warn,
      'error' => LogLevel.error,
      _ => LogLevel.info,
    };
    _sink(lvl, 'plugin:$pluginShortName', message);
  }

  static void _defaultSink(LogLevel level, String tag, String message) {
    final logger = Logger(tag);
    switch (level) {
      case LogLevel.debug:
        logger.debug(message);
      case LogLevel.info:
        logger.info(message);
      case LogLevel.warn:
        logger.warn(message);
      case LogLevel.error:
        logger.error(message);
    }
  }
}
```

- [ ] **Step 4: Run tests**

```bash
flutter test test/plugins/host/log_host_test.dart
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/host/log_host.dart test/plugins/host/log_host_test.dart
git commit -m "plugins(host): log_host — namespace + level routing with injectable sink"
```

---

### Task 5: `host.json` — parse + stringify

**Files:**
- Create: `lib/plugins/host/json_host.dart`
- Create: `test/plugins/host/json_host_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/plugins/host/json_host_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/plugins/host/json_host.dart';

void main() {
  test('parse decodes JSON to native Dart', () {
    expect(JsonHost.parse('{"a":1,"b":["x","y"]}'),
        {'a': 1, 'b': ['x', 'y']});
  });

  test('stringify encodes back to JSON', () {
    expect(JsonHost.stringify({'a': 1}), '{"a":1}');
  });

  test('parse rejects malformed JSON with FormatException', () {
    expect(() => JsonHost.parse('not json'), throwsFormatException);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/plugins/host/json_host_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/plugins/host/json_host.dart
import 'dart:convert';

class JsonHost {
  JsonHost._();

  static Object? parse(String text) => jsonDecode(text);

  static String stringify(Object? value) => jsonEncode(value);
}
```

- [ ] **Step 4: Run tests**

```bash
flutter test test/plugins/host/json_host_test.dart
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/host/json_host.dart test/plugins/host/json_host_test.dart
git commit -m "plugins(host): json_host — parse + stringify"
```

---

### Task 6: `host.url` — absolute URL resolution

**Files:**
- Create: `lib/plugins/host/url_host.dart`
- Create: `test/plugins/host/url_host_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/plugins/host/url_host_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/plugins/host/url_host.dart';

void main() {
  test('absolute resolves a relative path against a base', () {
    expect(
      UrlHost.absolute('/storage/key', 'https://upstream.example/it/master.m3u8'),
      'https://upstream.example/storage/key',
    );
  });

  test('absolute is a no-op on already-absolute URLs', () {
    expect(
      UrlHost.absolute('https://other.example/x', 'https://upstream.example/'),
      'https://other.example/x',
    );
  });

  test('absolute resolves protocol-relative URLs', () {
    expect(
      UrlHost.absolute('//cdn.example/x.ts', 'https://upstream.example/'),
      'https://cdn.example/x.ts',
    );
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/plugins/host/url_host_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/plugins/host/url_host.dart
class UrlHost {
  UrlHost._();

  /// Resolve a possibly-relative URL against a base, mirroring whatwg URL
  /// semantics. Uses the standard `Uri.resolve`.
  static String absolute(String maybeRelative, String base) {
    final baseUri = Uri.parse(base);
    return baseUri.resolve(maybeRelative).toString();
  }
}
```

- [ ] **Step 4: Run tests**

```bash
flutter test test/plugins/host/url_host_test.dart
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/host/url_host.dart test/plugins/host/url_host_test.dart
git commit -m "plugins(host): url_host — absolute URL resolution"
```

---

### Task 7: `host.crypto` — sha256, md5, hmac, base64, aesDecrypt (known-vector tests)

**Files:**
- Create: `lib/plugins/host/crypto_host.dart`
- Create: `test/plugins/host/crypto_host_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/plugins/host/crypto_host_test.dart
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/plugins/host/crypto_host.dart';

void main() {
  test('sha256 of empty string', () {
    expect(CryptoHost.sha256Hex(''),
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
  });

  test('sha256 of "hello"', () {
    expect(CryptoHost.sha256Hex('hello'),
        '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824');
  });

  test('md5 of empty string', () {
    expect(CryptoHost.md5Hex(''), 'd41d8cd98f00b204e9800998ecf8427e');
  });

  test('hmac sha256 known vector (RFC 4231 test 1)', () {
    final key = Uint8List.fromList(List.filled(20, 0x0b));
    final data = Uint8List.fromList('Hi There'.codeUnits);
    expect(
      CryptoHost.hmacHex('sha256', key, data),
      'b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7',
    );
  });

  test('base64 round-trip', () {
    expect(CryptoHost.base64Encode('Hello, world!'), 'SGVsbG8sIHdvcmxkIQ==');
  });

  test('aesDecrypt CBC with PKCS7 padding (HLS-style key)', () {
    // Key = 16 bytes of 0x42. IV = 16 bytes of 0x10.
    // Plaintext "yo" padded PKCS7 to 16 bytes, encrypted with AES-128-CBC.
    final key = Uint8List.fromList(List.filled(16, 0x42));
    final iv = Uint8List.fromList(List.filled(16, 0x10));
    // Pre-computed ciphertext for plaintext = "yo" + padding 14*0x0e:
    final ciphertext = Uint8List.fromList([
      0xe2, 0x05, 0xa6, 0x53, 0xb6, 0xfd, 0x52, 0x42,
      0xc7, 0x91, 0x05, 0x95, 0xc8, 0x4d, 0x66, 0x16,
    ]);
    final out = CryptoHost.aesDecryptCbc(ciphertext, key, iv);
    expect(String.fromCharCodes(out), 'yo');
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/plugins/host/crypto_host_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/plugins/host/crypto_host.dart
import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as c;
import 'package:pointycastle/export.dart' as pc;

class CryptoHost {
  CryptoHost._();

  static String sha256Hex(String input) {
    return c.sha256.convert(utf8.encode(input)).toString();
  }

  static String md5Hex(String input) {
    return c.md5.convert(utf8.encode(input)).toString();
  }

  /// HMAC over arbitrary bytes. `algorithm` is "sha1" or "sha256".
  static String hmacHex(String algorithm, List<int> key, List<int> data) {
    final hash = switch (algorithm) {
      'sha1' => c.sha1,
      'sha256' => c.sha256,
      _ => throw ArgumentError.value(algorithm, 'algorithm', 'unsupported'),
    };
    return c.Hmac(hash, key).convert(data).toString();
  }

  static String base64Encode(String input) {
    return base64.encode(utf8.encode(input));
  }

  /// AES-128/192/256-CBC decrypt with PKCS#7 unpadding.
  /// Used for HLS clear-key segment decryption (matches the v2 backend's
  /// streaming/drm.py behaviour).
  static Uint8List aesDecryptCbc(Uint8List ciphertext, Uint8List key, Uint8List iv) {
    final cipher = pc.PaddedBlockCipherImpl(
      pc.PKCS7Padding(),
      pc.CBCBlockCipher(pc.AESEngine()),
    );
    cipher.init(
      false,
      pc.PaddedBlockCipherParameters(
        pc.ParametersWithIV(pc.KeyParameter(key), iv),
        null,
      ),
    );
    return cipher.process(ciphertext);
  }
}
```

- [ ] **Step 4: Run tests**

```bash
flutter test test/plugins/host/crypto_host_test.dart
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/host/crypto_host.dart test/plugins/host/crypto_host_test.dart
git commit -m "plugins(host): crypto_host — sha256/md5/hmac/base64/AES-CBC with known-vector tests"
```

---

### Task 8: `host.http.fetch` — wraps dio (10s timeout, 10MB cap, 5 redirects)

**Files:**
- Create: `lib/plugins/host/http_host.dart`
- Create: `test/plugins/host/http_host_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/plugins/host/http_host_test.dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/plugins/host/http_host.dart';

class _DioMock extends Mock implements Dio {}

class _FakeOptions extends Fake implements RequestOptions {}

void main() {
  setUpAll(() => registerFallbackValue(_FakeOptions()));

  test('GET passes URL and headers, returns shaped response', () async {
    final dio = _DioMock();
    when(() => dio.fetch<dynamic>(any())).thenAnswer((_) async => Response(
          requestOptions: RequestOptions(path: 'https://x/'),
          statusCode: 200,
          data: 'hello',
          headers: Headers.fromMap({
            'content-type': ['text/plain'],
          }),
          realUri: Uri.parse('https://x/'),
        ));
    final host = HttpHost.test(dio);

    final result = await host.fetch('https://x/', {
      'method': 'GET',
      'headers': {'Referer': 'https://up'},
    });

    expect(result['status'], 200);
    expect(result['body'], 'hello');
    expect(result['headers']['content-type'], 'text/plain');
    expect(result['finalUrl'], 'https://x/');
  });

  test('non-2xx still resolves (does not throw); status preserved', () async {
    final dio = _DioMock();
    when(() => dio.fetch<dynamic>(any())).thenAnswer((_) async => Response(
          requestOptions: RequestOptions(path: 'https://x/'),
          statusCode: 404,
          data: 'not found',
          realUri: Uri.parse('https://x/'),
        ));
    final host = HttpHost.test(dio);
    final result = await host.fetch('https://x/', {'method': 'GET'});
    expect(result['status'], 404);
    expect(result['body'], 'not found');
  });

  test('cookies array reflects Set-Cookie headers', () async {
    final dio = _DioMock();
    when(() => dio.fetch<dynamic>(any())).thenAnswer((_) async => Response(
          requestOptions: RequestOptions(path: 'https://x/'),
          statusCode: 200,
          data: '',
          headers: Headers.fromMap({
            'set-cookie': ['session=abc; Path=/', 'pref=dark'],
          }),
          realUri: Uri.parse('https://x/'),
        ));
    final host = HttpHost.test(dio);
    final result = await host.fetch('https://x/', {'method': 'GET'});
    expect(result['cookies'], {'session': 'abc', 'pref': 'dark'});
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/plugins/host/http_host_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/plugins/host/http_host.dart
import 'package:dio/dio.dart';

class HttpHost {
  HttpHost._(this._dio);

  /// Production constructor — owns its own dio with the strict defaults.
  factory HttpHost() {
    final dio = Dio(BaseOptions(
      connectTimeout: const Duration(seconds: 10),
      sendTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 10),
      followRedirects: true,
      maxRedirects: 5,
      validateStatus: (_) => true,
      responseType: ResponseType.plain,
    ));
    return HttpHost._(dio);
  }

  /// Test constructor — injectable dio.
  HttpHost.test(Dio dio) : _dio = dio;

  final Dio _dio;
  static const int _maxBodyBytes = 10 * 1024 * 1024; // 10MB cap

  /// `init` shape: `{ method?, headers?, body?, cookies? }` — all optional.
  Future<Map<String, dynamic>> fetch(String url, Map<String, dynamic> init) async {
    final method = (init['method'] as String?)?.toUpperCase() ?? 'GET';
    final headers = Map<String, dynamic>.from(
      (init['headers'] as Map?) ?? <String, dynamic>{},
    );

    // Merge cookies (if any) into a Cookie header, joined with ; .
    final cookieIn = init['cookies'];
    if (cookieIn is Map && cookieIn.isNotEmpty) {
      headers['Cookie'] = cookieIn.entries
          .map((e) => '${e.key}=${e.value}')
          .join('; ');
    }

    final options = RequestOptions(
      path: url,
      method: method,
      headers: headers,
      data: init['body'],
      followRedirects: true,
      maxRedirects: 5,
      validateStatus: (_) => true,
      responseType: ResponseType.plain,
    );

    final resp = await _dio.fetch<dynamic>(options);

    final body = resp.data?.toString() ?? '';
    if (body.length > _maxBodyBytes) {
      throw StateError(
        'http_host: response body exceeds 10MB cap (${body.length} bytes)',
      );
    }

    return {
      'status': resp.statusCode ?? 0,
      'headers': _flattenHeaders(resp.headers),
      'body': body,
      'cookies': _parseSetCookie(resp.headers),
      'finalUrl': resp.realUri.toString(),
    };
  }

  Map<String, String> _flattenHeaders(Headers h) {
    final out = <String, String>{};
    h.forEach((name, values) => out[name.toLowerCase()] = values.join(', '));
    return out;
  }

  Map<String, String> _parseSetCookie(Headers h) {
    final out = <String, String>{};
    final raw = h['set-cookie'];
    if (raw == null) return out;
    for (final line in raw) {
      // First name=value pair before any "; " attribute.
      final firstSemi = line.indexOf(';');
      final pair = firstSemi >= 0 ? line.substring(0, firstSemi) : line;
      final eq = pair.indexOf('=');
      if (eq <= 0) continue;
      out[pair.substring(0, eq).trim()] = pair.substring(eq + 1).trim();
    }
    return out;
  }
}
```

- [ ] **Step 4: Run tests**

```bash
flutter test test/plugins/host/http_host_test.dart
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/host/http_host.dart test/plugins/host/http_host_test.dart
git commit -m "plugins(host): http_host — dio with 10s timeout, 10MB cap, 5 redirects"
```

---

### Task 9: `host.html.parse` — cheerio-shaped wrapper around package:html

**Files:**
- Create: `lib/plugins/host/html_host.dart`
- Create: `test/plugins/host/html_host_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/plugins/host/html_host_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/plugins/host/html_host.dart';

void main() {
  const sample = '''
<html>
  <body>
    <ul class="titles">
      <li data-id="42"><a href="/title/42">First</a></li>
      <li data-id="43"><a href="/title/43">Second</a></li>
    </ul>
  </body>
</html>
''';

  test('find returns matching elements with text + attr access', () {
    final doc = HtmlHost.parse(sample);
    final items = doc.find('li');
    expect(items, hasLength(2));
    expect(items[0].text(), 'First');
    expect(items[0].attr('data-id'), '42');
    expect(items[1].attr('data-id'), '43');
  });

  test('querySelector returns first match or null', () {
    final doc = HtmlHost.parse(sample);
    expect(doc.querySelector('a')?.attr('href'), '/title/42');
    expect(doc.querySelector('.does-not-exist'), isNull);
  });

  test('html() returns inner HTML of an element', () {
    final doc = HtmlHost.parse(sample);
    final ul = doc.find('ul.titles').single;
    expect(ul.html(), contains('<li data-id="42">'));
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/plugins/host/html_host_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/plugins/host/html_host.dart
import 'package:html/dom.dart' as dom;
import 'package:html/parser.dart' as parser;

/// Minimal cheerio-shaped Element wrapper. Each method matches what the
/// plugin contract documents.
class HtmlElement {
  HtmlElement(this._node);
  final dom.Element _node;

  String text() => _node.text;
  String html() => _node.innerHtml;

  String? attr(String name) => _node.attributes[name];

  List<HtmlElement> find(String selector) {
    return _node.querySelectorAll(selector).map(HtmlElement.new).toList();
  }
}

class HtmlDocument {
  HtmlDocument(this._doc);
  final dom.Document _doc;

  List<HtmlElement> find(String selector) {
    return _doc.querySelectorAll(selector).map(HtmlElement.new).toList();
  }

  HtmlElement? querySelector(String selector) {
    final node = _doc.querySelector(selector);
    return node == null ? null : HtmlElement(node);
  }
}

class HtmlHost {
  HtmlHost._();

  static HtmlDocument parse(String text) {
    return HtmlDocument(parser.parse(text));
  }
}
```

- [ ] **Step 4: Run tests**

```bash
flutter test test/plugins/host/html_host_test.dart
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/host/html_host.dart test/plugins/host/html_host_test.dart
git commit -m "plugins(host): html_host — cheerio-shaped wrapper around package:html"
```

---

### Task 10: `host.storage` — namespaced get/set/delete via PluginKvDao

**Files:**
- Create: `lib/plugins/host/storage_host.dart`
- Create: `test/plugins/host/storage_host_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/plugins/host/storage_host_test.dart
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/data/local/database.dart';
import 'package:streamload_client/plugins/host/storage_host.dart';

void main() {
  late StreamloadDatabase db;
  late StorageHost host;

  setUp(() {
    db = StreamloadDatabase.test(NativeDatabase.memory());
    host = StorageHost(db.pluginKvDao);
  });

  tearDown(() => db.close());

  test('set + get round-trip per plugin', () async {
    await host.set('echo', 'session', 'abc');
    expect(await host.get('echo', 'session'), 'abc');
    expect(await host.get('echo', 'missing'), isNull);
  });

  test('namespaces stay isolated per plugin', () async {
    await host.set('echo', 'k', 'echo_val');
    await host.set('sc', 'k', 'sc_val');
    expect(await host.get('echo', 'k'), 'echo_val');
    expect(await host.get('sc', 'k'), 'sc_val');
  });

  test('delete drops the row', () async {
    await host.set('echo', 'k', 'v');
    await host.delete('echo', 'k');
    expect(await host.get('echo', 'k'), isNull);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/plugins/host/storage_host_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/plugins/host/storage_host.dart
import '../../data/local/daos/plugin_kv_dao.dart';

class StorageHost {
  StorageHost(this._dao);
  final PluginKvDao _dao;

  Future<String?> get(String pluginShortName, String key) {
    return _dao.get(pluginShortName, key);
  }

  Future<void> set(String pluginShortName, String key, String value) {
    return _dao.set(pluginShortName, key, value);
  }

  Future<void> delete(String pluginShortName, String key) {
    return _dao.delete(pluginShortName, key);
  }
}
```

- [ ] **Step 4: Run tests**

```bash
flutter test test/plugins/host/storage_host_test.dart
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/host/storage_host.dart test/plugins/host/storage_host_test.dart
git commit -m "plugins(host): storage_host — namespaced get/set/delete via PluginKvDao"
```

---

## Phase C — Plugin meta + typed Plugin wrapper

### Task 11: `meta.dart` — freezed PluginMeta + validation

**Files:**
- Create: `lib/plugins/meta.dart`
- Create: `test/plugins/meta_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/plugins/meta_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/plugins/meta.dart';

void main() {
  test('accepts a valid meta payload', () {
    final m = PluginMeta.fromJson({
      'short_name': 'echo',
      'display_name': 'Echo',
      'version': '1.0.0',
      'api_version': 1,
      'capabilities': ['movie'],
    });
    expect(m.shortName, 'echo');
    expect(m.capabilities, ['movie']);
  });

  test('validate rejects bad short_name', () {
    final result = PluginMeta.validate({
      'short_name': 'BAD-NAME',
      'display_name': 'X',
      'version': '1.0.0',
      'api_version': 1,
      'capabilities': ['movie'],
    });
    expect(result, contains('short_name'));
  });

  test('validate rejects api_version other than 1', () {
    final result = PluginMeta.validate({
      'short_name': 'echo',
      'display_name': 'Echo',
      'version': '1.0.0',
      'api_version': 2,
      'capabilities': ['movie'],
    });
    expect(result, contains('api_version'));
  });

  test('validate rejects unknown capability', () {
    final result = PluginMeta.validate({
      'short_name': 'echo',
      'display_name': 'Echo',
      'version': '1.0.0',
      'api_version': 1,
      'capabilities': ['movie:made_up'],
    });
    expect(result, contains('capabilities'));
  });

  test('validate rejects bad semver', () {
    final result = PluginMeta.validate({
      'short_name': 'echo',
      'display_name': 'Echo',
      'version': 'not-semver',
      'api_version': 1,
      'capabilities': ['movie'],
    });
    expect(result, contains('version'));
  });

  test('validate returns null for all-good payload', () {
    expect(PluginMeta.validate({
      'short_name': 'echo',
      'display_name': 'Echo',
      'version': '1.0.0',
      'api_version': 1,
      'capabilities': ['movie', 'tv:anime'],
    }), isNull);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/plugins/meta_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/plugins/meta.dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'meta.freezed.dart';
part 'meta.g.dart';

const Set<String> kAllowedCapabilities = {
  'movie',
  'movie:anime',
  'movie:kids',
  'movie:documentary',
  'tv',
  'tv:anime',
  'tv:kids',
  'tv:documentary',
  'tv:reality',
  'tv:news',
  'tv:sport',
};

final RegExp _shortNameRe = RegExp(r'^[a-z][a-z0-9_]{1,15}$');
final RegExp _semverRe =
    RegExp(r'^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$');

@freezed
class PluginMeta with _$PluginMeta {
  const factory PluginMeta({
    @JsonKey(name: 'short_name') required String shortName,
    @JsonKey(name: 'display_name') required String displayName,
    required String version,
    @JsonKey(name: 'api_version') required int apiVersion,
    required List<String> capabilities,
    @JsonKey(name: 'min_app_version') String? minAppVersion,
  }) = _PluginMeta;

  factory PluginMeta.fromJson(Map<String, dynamic> json) =>
      _$PluginMetaFromJson(json);

  /// Returns null if the payload satisfies the contract; otherwise a
  /// human-readable string describing the first failure (substring will
  /// include the offending field name).
  static String? validate(Map<String, dynamic> json) {
    final shortName = json['short_name'];
    if (shortName is! String || !_shortNameRe.hasMatch(shortName)) {
      return 'meta.short_name must match ${_shortNameRe.pattern}';
    }
    final displayName = json['display_name'];
    if (displayName is! String || displayName.isEmpty) {
      return 'meta.display_name must be a non-empty string';
    }
    final version = json['version'];
    if (version is! String || !_semverRe.hasMatch(version)) {
      return 'meta.version must be semver';
    }
    final apiVersion = json['api_version'];
    if (apiVersion != 1) {
      return 'meta.api_version must be 1';
    }
    final caps = json['capabilities'];
    if (caps is! List || caps.isEmpty) {
      return 'meta.capabilities must be a non-empty array';
    }
    for (final c in caps) {
      if (c is! String || !kAllowedCapabilities.contains(c)) {
        return 'meta.capabilities contains unknown value: $c';
      }
    }
    return null;
  }
}
```

- [ ] **Step 4: Run code-gen + tests**

```bash
dart run build_runner build --delete-conflicting-outputs
flutter test test/plugins/meta_test.dart
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/meta.dart lib/plugins/meta.freezed.dart lib/plugins/meta.g.dart test/plugins/meta_test.dart
git commit -m "plugins: PluginMeta freezed model + validate() against the closed contract"
```

---

### Task 12: `plugin.dart` — typed `Plugin` Dart wrapper

**Files:**
- Create: `lib/plugins/plugin.dart`

This file declares the type only — it's exercised end-to-end in the runtime tests (Tasks 14, 17). No standalone test here.

- [ ] **Step 1: Write the wrapper**

```dart
// lib/plugins/plugin.dart
import 'meta.dart';

/// Forward declaration of the JS-evaluating callable. PluginRuntime supplies
/// the real implementation.
typedef PluginCall = Future<Object?> Function(
  String pluginShortName,
  String functionName,
  List<Object?> args,
);

/// Typed Dart-side handle to one mounted JS plugin.
///
/// Created by PluginRuntime; instances are cheap and disposable. Calling a
/// method on a stale instance after the plugin has been unmounted will throw
/// from the underlying runtime.
class Plugin {
  Plugin({
    required this.meta,
    required PluginCall call,
  }) : _call = call;

  final PluginMeta meta;
  final PluginCall _call;

  String get shortName => meta.shortName;

  Future<List<Map<String, dynamic>>> search(String query) async {
    final raw = await _call(meta.shortName, 'search', [query]);
    return (raw as List).cast<Map<String, dynamic>>();
  }

  Future<List<Map<String, dynamic>>> getSeasons(Map<String, dynamic> entry) async {
    final raw = await _call(meta.shortName, 'getSeasons', [entry]);
    return (raw as List).cast<Map<String, dynamic>>();
  }

  Future<List<Map<String, dynamic>>> getEpisodes(Map<String, dynamic> season) async {
    final raw = await _call(meta.shortName, 'getEpisodes', [season]);
    return (raw as List).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> getStreams(Map<String, dynamic> target) async {
    final raw = await _call(meta.shortName, 'getStreams', [target]);
    return (raw as Map).cast<String, dynamic>();
  }
}
```

- [ ] **Step 2: Verify analyze**

```bash
flutter analyze lib/plugins/plugin.dart
```

Expected: `No issues found!`.

- [ ] **Step 3: Commit**

```bash
git add lib/plugins/plugin.dart
git commit -m "plugins: Plugin Dart wrapper (typed bindings to the 4 contract functions)"
```

---

## Phase D — JS runtime + host bridge

### Task 13: `host_api.dart` — central dispatcher for `host_call` channel

**Files:**
- Create: `lib/plugins/host_api.dart`

The dispatcher takes a JSON payload `{plugin, module, method, args}` and routes to the right host module. Tested transitively by the runtime tests in Task 14.

- [ ] **Step 1: Write the dispatcher**

```dart
// lib/plugins/host_api.dart
import 'dart:convert';
import 'dart:typed_data';

import 'host/crypto_host.dart';
import 'host/html_host.dart';
import 'host/http_host.dart';
import 'host/json_host.dart';
import 'host/log_host.dart';
import 'host/storage_host.dart';
import 'host/url_host.dart';

/// Bundles the host modules into one namespace. `PluginRuntime` hands the
/// `dispatch` method to flutter_js as the `host_call` channel handler.
class HostApi {
  HostApi({
    required this.http,
    required this.storage,
    required this.log,
    HtmlHost? html,
    JsonHost? json,
    UrlHost? url,
    CryptoHost? crypto,
  });

  final HttpHost http;
  final StorageHost storage;
  final LogHost log;

  /// Cache of recently-parsed HTML docs, keyed by an opaque handle.
  /// Plugins call host.html.parse(text) → returns handle. Subsequent
  /// host.html.find(handle, selector) etc. dereference here.
  final Map<int, HtmlDocument> _htmlDocs = {};
  final Map<int, HtmlElement> _htmlElements = {};
  int _htmlCounter = 0;

  /// Channel handler. Receives a JSON-stringified `{plugin, module, method, args}`
  /// and returns a JSON-stringified response. Errors are returned as
  /// `{__error: 'message'}`.
  Future<String> dispatch(String payloadJson) async {
    try {
      final payload = jsonDecode(payloadJson) as Map<String, dynamic>;
      final plugin = payload['plugin'] as String;
      final module = payload['module'] as String;
      final method = payload['method'] as String;
      final args = (payload['args'] as List?) ?? const [];

      final result = await _route(plugin, module, method, args);
      return jsonEncode({'value': result});
    } catch (e) {
      return jsonEncode({'error': e.toString()});
    }
  }

  Future<Object?> _route(
    String plugin,
    String module,
    String method,
    List<dynamic> args,
  ) async {
    switch (module) {
      case 'log':
        log.handle(plugin, method, args.first as String);
        return null;
      case 'http':
        if (method != 'fetch') {
          throw StateError('http: unknown method $method');
        }
        return http.fetch(args[0] as String, args[1] as Map<String, dynamic>);
      case 'storage':
        switch (method) {
          case 'get':
            return storage.get(plugin, args[0] as String);
          case 'set':
            await storage.set(plugin, args[0] as String, args[1] as String);
            return null;
          case 'delete':
            await storage.delete(plugin, args[0] as String);
            return null;
          default:
            throw StateError('storage: unknown method $method');
        }
      case 'json':
        switch (method) {
          case 'parse':
            return JsonHost.parse(args[0] as String);
          case 'stringify':
            return JsonHost.stringify(args[0]);
          default:
            throw StateError('json: unknown method $method');
        }
      case 'url':
        if (method != 'absolute') throw StateError('url: unknown method $method');
        return UrlHost.absolute(args[0] as String, args[1] as String);
      case 'crypto':
        switch (method) {
          case 'sha256Hex':
            return CryptoHost.sha256Hex(args[0] as String);
          case 'md5Hex':
            return CryptoHost.md5Hex(args[0] as String);
          case 'hmacHex':
            return CryptoHost.hmacHex(
              args[0] as String,
              (args[1] as List).cast<int>(),
              (args[2] as List).cast<int>(),
            );
          case 'base64Encode':
            return CryptoHost.base64Encode(args[0] as String);
          case 'aesDecryptCbc':
            final out = CryptoHost.aesDecryptCbc(
              Uint8List.fromList((args[0] as List).cast<int>()),
              Uint8List.fromList((args[1] as List).cast<int>()),
              Uint8List.fromList((args[2] as List).cast<int>()),
            );
            return out.toList(); // JSON-friendly
          default:
            throw StateError('crypto: unknown method $method');
        }
      case 'html':
        return _routeHtml(method, args);
      default:
        throw StateError('unknown host module: $module');
    }
  }

  Object? _routeHtml(String method, List<dynamic> args) {
    switch (method) {
      case 'parse':
        final doc = HtmlHost.parse(args[0] as String);
        final h = ++_htmlCounter;
        _htmlDocs[h] = doc;
        return {'__doc': h};
      case 'doc.find':
        final doc = _htmlDocs[args[0] as int]!;
        final results = doc.find(args[1] as String);
        return _registerElements(results);
      case 'doc.querySelector':
        final doc = _htmlDocs[args[0] as int]!;
        final el = doc.querySelector(args[1] as String);
        if (el == null) return null;
        final h = ++_htmlCounter;
        _htmlElements[h] = el;
        return {'__el': h};
      case 'el.find':
        final el = _htmlElements[args[0] as int]!;
        final results = el.find(args[1] as String);
        return _registerElements(results);
      case 'el.text':
        return _htmlElements[args[0] as int]!.text();
      case 'el.html':
        return _htmlElements[args[0] as int]!.html();
      case 'el.attr':
        return _htmlElements[args[0] as int]!.attr(args[1] as String);
      case 'release':
        // Plugin tells us it's done with a doc/element handle. Best-effort GC.
        _htmlDocs.remove(args[0]);
        _htmlElements.remove(args[0]);
        return null;
      default:
        throw StateError('html: unknown method $method');
    }
  }

  List<Map<String, int>> _registerElements(List<HtmlElement> els) {
    return els.map((e) {
      final h = ++_htmlCounter;
      _htmlElements[h] = e;
      return {'__el': h};
    }).toList();
  }
}
```

- [ ] **Step 2: Verify analyze**

```bash
flutter analyze lib/plugins/host_api.dart
```

Expected: `No issues found!`.

- [ ] **Step 3: Commit**

```bash
git add lib/plugins/host_api.dart
git commit -m "plugins: host_api dispatcher — JSON-bridges every host.* call to its module"
```

---

### Task 14: `runtime.dart` — JsRuntime wrapper + mount/unmount + atomic-swap

**Files:**
- Create: `lib/plugins/runtime.dart`
- Create: `test/plugins/runtime_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/plugins/runtime_test.dart
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/data/local/database.dart';
import 'package:streamload_client/plugins/host/http_host.dart';
import 'package:streamload_client/plugins/host/log_host.dart';
import 'package:streamload_client/plugins/host/storage_host.dart';
import 'package:streamload_client/plugins/host_api.dart';
import 'package:streamload_client/plugins/runtime.dart';

const _echoSource = '''
export const meta = {
  short_name: "echo",
  display_name: "Echo",
  version: "1.0.0",
  api_version: 1,
  capabilities: ["movie"],
};

export async function search(query) {
  return [{ id: "echo-1", title: query, type: "movie", service: "echo", url: "https://example.invalid/" + query }];
}

export async function getSeasons(_entry) { return []; }
export async function getEpisodes(_season) { return []; }

export async function getStreams(entry) {
  return { manifest_url: "https://example.invalid/master.m3u8", headers: {} };
}
''';

void main() {
  late StreamloadDatabase db;
  late HostApi hostApi;
  late PluginRuntime runtime;

  setUp(() async {
    db = StreamloadDatabase.test(NativeDatabase.memory());
    hostApi = HostApi(
      http: HttpHost(),
      storage: StorageHost(db.pluginKvDao),
      log: LogHost(sink: (_, __, ___) {}),
    );
    runtime = await PluginRuntime.create(hostApi: hostApi);
  });

  tearDown(() async {
    await runtime.dispose();
    await db.close();
  });

  test('mount + Plugin.search returns the echo synthetic shape', () async {
    final plugin = await runtime.mount(_echoSource);
    expect(plugin.meta.shortName, 'echo');
    final results = await plugin.search('hello');
    expect(results, hasLength(1));
    expect(results.first['title'], 'hello');
    expect(results.first['service'], 'echo');
  });

  test('mount validates meta and rejects bad source', () async {
    expect(
      () => runtime.mount('export const meta = { short_name: "BAD-NAME", display_name: "x", version: "1.0.0", api_version: 1, capabilities: ["movie"] };'),
      throwsA(isA<StateError>().having((e) => e.message, 'message', contains('short_name'))),
    );
  });

  test('atomic swap: a failed mount leaves the previous version active', () async {
    await runtime.mount(_echoSource);
    final before = await runtime.callable('echo')!.search('a');
    expect(before.first['title'], 'a');

    // Try to mount a corrupt source for the same short_name.
    expect(
      () => runtime.mount(_echoSource.replaceFirst(
        'capabilities: ["movie"]',
        'capabilities: ["movie:made_up"]',
      )),
      throwsA(isA<StateError>().having((e) => e.message, 'message', contains('capabilities'))),
    );

    // Original still callable.
    final after = await runtime.callable('echo')!.search('b');
    expect(after.first['title'], 'b');
  });

  test('unmount drops the plugin', () async {
    await runtime.mount(_echoSource);
    await runtime.unmount('echo');
    expect(runtime.callable('echo'), isNull);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/plugins/runtime_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/plugins/runtime.dart
import 'dart:convert';

import 'package:flutter_js/flutter_js.dart';

import 'host_api.dart';
import 'meta.dart';
import 'plugin.dart';

/// Hosts the QuickJS runtime + every mounted plugin. One instance per app.
///
/// Plugin source is vanilla ESM; we transform `export ` declarations into
/// assignments on a per-plugin exports object, then evaluate the result and
/// stash it under `globalThis.__sl_plugins[shortName]`.
class PluginRuntime {
  PluginRuntime._(this._js, this._hostApi);

  static Future<PluginRuntime> create({required HostApi hostApi}) async {
    final js = getJavascriptRuntime();
    js.onMessage('host_call', (dynamic args) async {
      // flutter_js passes the raw payload; our JS shim sends a JSON string.
      final payload = args is String ? args : jsonEncode(args);
      return hostApi.dispatch(payload);
    });
    final runtime = PluginRuntime._(js, hostApi);
    await runtime._installShim();
    return runtime;
  }

  final JavascriptRuntime _js;
  // ignore: unused_field
  final HostApi _hostApi;

  final Map<String, Plugin> _plugins = {};

  /// Install the per-runtime shim that makes `host.*` Promise-based and
  /// gives plugins a `__sl_export` object to write into.
  Future<void> _installShim() async {
    const shim = r'''
      (function() {
        if (globalThis.__sl_plugins) return;
        globalThis.__sl_plugins = {};
        globalThis.__sl_currentPlugin = null;
        function call(module, method, args) {
          const plugin = globalThis.__sl_currentPlugin;
          const payload = JSON.stringify({plugin, module, method, args});
          return sendMessage('host_call', payload).then(function(raw) {
            const out = JSON.parse(raw);
            if (out.error) throw new Error(out.error);
            return out.value;
          });
        }
        globalThis.host = {
          log: {
            debug: (m) => call('log', 'debug', [m]),
            info:  (m) => call('log', 'info',  [m]),
            warn:  (m) => call('log', 'warn',  [m]),
            error: (m) => call('log', 'error', [m]),
          },
          http: {
            fetch: (url, init) => call('http', 'fetch', [url, init || {}]),
          },
          storage: {
            get:    (k)    => call('storage', 'get',    [k]),
            set:    (k, v) => call('storage', 'set',    [k, v]),
            delete: (k)    => call('storage', 'delete', [k]),
          },
          json: {
            parse:     (s) => call('json', 'parse',     [s]),
            stringify: (o) => call('json', 'stringify', [o]),
          },
          url: {
            absolute: (rel, base) => call('url', 'absolute', [rel, base]),
          },
          crypto: {
            sha256Hex:    (s)            => call('crypto', 'sha256Hex',    [s]),
            md5Hex:       (s)            => call('crypto', 'md5Hex',       [s]),
            hmacHex:      (algo, k, d)   => call('crypto', 'hmacHex',      [algo, Array.from(k), Array.from(d)]),
            base64Encode: (s)            => call('crypto', 'base64Encode', [s]),
            aesDecryptCbc:(ct, k, iv)    => call('crypto', 'aesDecryptCbc',[Array.from(ct), Array.from(k), Array.from(iv)]).then(arr => Uint8Array.from(arr)),
          },
          html: {
            parse: async (text) => {
              const ref = await call('html', 'parse', [text]);
              return wrapDoc(ref.__doc);
            },
          },
        };
        function wrapDoc(h) {
          return {
            find: async (sel) => (await call('html', 'doc.find', [h, sel])).map(r => wrapEl(r.__el)),
            querySelector: async (sel) => {
              const ref = await call('html', 'doc.querySelector', [h, sel]);
              return ref == null ? null : wrapEl(ref.__el);
            },
          };
        }
        function wrapEl(h) {
          return {
            find: async (sel) => (await call('html', 'el.find', [h, sel])).map(r => wrapEl(r.__el)),
            text: () => call('html', 'el.text', [h]),
            html: () => call('html', 'el.html', [h]),
            attr: (n) => call('html', 'el.attr', [h, n]),
          };
        }
      })();
    ''';
    final result = await _js.evaluateAsync(shim);
    _js.executePendingJob();
    final s = result.stringResult;
    if (result.isError) {
      throw StateError('plugin runtime shim failed: $s');
    }
  }

  /// Mount a plugin from raw ESM source. Atomic: if anything fails (parse,
  /// meta validation, evaluation), the previous version (if any) stays active.
  Future<Plugin> mount(String source) async {
    // Phase 1: extract & validate meta by evaluating in isolation.
    final probeId = '__sl_probe_${DateTime.now().microsecondsSinceEpoch}';
    final probeBlock = '''
      globalThis.$probeId = (function() {
        const exports = {};
        ${_stripExports(source)}
        return exports;
      })();
      JSON.stringify(globalThis.$probeId.meta);
    ''';
    final probe = await _js.evaluateAsync(probeBlock);
    _js.executePendingJob();
    if (probe.isError) {
      throw StateError('plugin parse failed: ${probe.stringResult}');
    }
    final metaJson = jsonDecode(probe.stringResult) as Map<String, dynamic>;
    final err = PluginMeta.validate(metaJson);
    if (err != null) {
      // Drop the probe and abort.
      await _js.evaluateAsync('delete globalThis.$probeId');
      throw StateError(err);
    }
    final meta = PluginMeta.fromJson(metaJson);

    // Phase 2: commit — copy probe object to the canonical slot, drop probe.
    final commitBlock = '''
      globalThis.__sl_plugins[${jsonEncode(meta.shortName)}] = globalThis.$probeId;
      delete globalThis.$probeId;
      true;
    ''';
    final commit = await _js.evaluateAsync(commitBlock);
    _js.executePendingJob();
    if (commit.isError) {
      throw StateError('plugin commit failed: ${commit.stringResult}');
    }

    final plugin = Plugin(meta: meta, call: _callJsFunction);
    _plugins[meta.shortName] = plugin;
    return plugin;
  }

  Future<void> unmount(String shortName) async {
    _plugins.remove(shortName);
    await _js.evaluateAsync(
      'delete globalThis.__sl_plugins[${jsonEncode(shortName)}]; true;',
    );
    _js.executePendingJob();
  }

  Plugin? callable(String shortName) => _plugins[shortName];

  Iterable<Plugin> get all => _plugins.values;

  Future<void> dispose() async {
    _js.dispose();
  }

  /// Execute `globalThis.__sl_plugins[shortName].functionName(...args)` and
  /// return the JSON-parsed result.
  Future<Object?> _callJsFunction(
    String shortName,
    String functionName,
    List<Object?> args,
  ) async {
    final stub = '''
      (async function() {
        globalThis.__sl_currentPlugin = ${jsonEncode(shortName)};
        try {
          const fn = globalThis.__sl_plugins[${jsonEncode(shortName)}].${functionName};
          const out = await fn.apply(null, ${jsonEncode(args)});
          return JSON.stringify(out === undefined ? null : out);
        } finally {
          globalThis.__sl_currentPlugin = null;
        }
      })();
    ''';
    final result = await _js.evaluateAsync(stub);
    _js.executePendingJob();
    if (result.isError) {
      throw StateError(
        'plugin $shortName.$functionName failed: ${result.stringResult}',
      );
    }
    return jsonDecode(result.stringResult);
  }

  /// Strip the `export ` keyword from `export const`, `export async function`,
  /// and `export function` declarations, leaving plain assignments / function
  /// declarations whose names land in the surrounding IIFE's scope.
  ///
  /// We then make `exports.<name> = <name>` for the canonical exports we care
  /// about so the IIFE can return them.
  static String _stripExports(String source) {
    var stripped = source
        .replaceAll(RegExp(r'^\s*export\s+const\s+', multiLine: true), 'const ')
        .replaceAll(RegExp(r'^\s*export\s+let\s+', multiLine: true), 'let ')
        .replaceAll(RegExp(r'^\s*export\s+async\s+function\s+', multiLine: true),
            'async function ')
        .replaceAll(RegExp(r'^\s*export\s+function\s+', multiLine: true),
            'function ');
    // After the source body, copy the four contract names + meta into
    // exports if they were declared.
    return '''
$stripped

if (typeof meta !== "undefined") exports.meta = meta;
if (typeof search !== "undefined") exports.search = search;
if (typeof getSeasons !== "undefined") exports.getSeasons = getSeasons;
if (typeof getEpisodes !== "undefined") exports.getEpisodes = getEpisodes;
if (typeof getStreams !== "undefined") exports.getStreams = getStreams;
''';
  }
}
```

- [ ] **Step 4: Run tests**

```bash
flutter test test/plugins/runtime_test.dart
```

Expected: 4 tests pass. The first test confirms the IIFE strip + mount + JS-call round trip works end-to-end with the echo fixture-shaped source.

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/runtime.dart test/plugins/runtime_test.dart
git commit -m "plugins: PluginRuntime — JS sandbox + mount/unmount + atomic-swap"
```

---

## Phase E — GitHub fetch + registry diff + loader

### Task 15: `github_client.dart` — fetch registry + raw plugin file with PAT

**Files:**
- Create: `lib/plugins/github_client.dart`

This is a thin dio wrapper. No standalone test — covered transitively by Task 17's loader test with a mocked GitHub client.

- [ ] **Step 1: Write the client**

```dart
// lib/plugins/github_client.dart
import 'dart:convert';

import 'package:dio/dio.dart';

class GithubClient {
  GithubClient({required this.owner, required this.repo, required this.token, Dio? dio})
      : _dio = dio ??
            Dio(BaseOptions(
              baseUrl: 'https://api.github.com',
              headers: {
                'Accept': 'application/vnd.github.v3+json',
                'Authorization': 'Bearer $token',
                'X-GitHub-Api-Version': '2022-11-28',
              },
              connectTimeout: const Duration(seconds: 10),
              receiveTimeout: const Duration(seconds: 30),
              validateStatus: (_) => true,
            ));

  final String owner;
  final String repo;
  final String token;
  final Dio _dio;

  /// GET /repos/{owner}/{repo}/contents/{path} — returns the parsed JSON body
  /// (which has `{ name, sha, content (base64), encoding, ... }` for files).
  Future<Map<String, dynamic>> getContents(String path) async {
    final resp = await _dio.get<dynamic>('/repos/$owner/$repo/contents/$path');
    if (resp.statusCode != 200) {
      throw StateError(
        'github: GET contents/$path → ${resp.statusCode} ${resp.data}',
      );
    }
    return resp.data as Map<String, dynamic>;
  }

  /// Fetch `registry.json` decoded from base64.
  Future<Map<String, dynamic>> getRegistry() async {
    final raw = await getContents('registry.json');
    final encoded = (raw['content'] as String).replaceAll('\n', '');
    final decoded = utf8.decode(base64.decode(encoded));
    return jsonDecode(decoded) as Map<String, dynamic>;
  }

  /// Fetch a plugin .js file as raw text (uses `Accept: application/vnd.github.v3.raw`).
  Future<String> getPluginSource(String filePath) async {
    final resp = await _dio.get<dynamic>(
      '/repos/$owner/$repo/contents/$filePath',
      options: Options(
        headers: {'Accept': 'application/vnd.github.v3.raw'},
        responseType: ResponseType.plain,
      ),
    );
    if (resp.statusCode != 200) {
      throw StateError(
        'github: GET raw $filePath → ${resp.statusCode} ${resp.data}',
      );
    }
    return resp.data as String;
  }

  /// Sanity check the PAT can read the registry. Used by the onboarding wizard.
  /// Returns true on 200, false on 401/403, throws on anything else.
  Future<bool> verifyAccess() async {
    final resp = await _dio.get<dynamic>('/repos/$owner/$repo/contents/registry.json');
    if (resp.statusCode == 200) return true;
    if (resp.statusCode == 401 || resp.statusCode == 403 || resp.statusCode == 404) {
      return false;
    }
    throw StateError('github: verify failed → ${resp.statusCode}');
  }
}
```

- [ ] **Step 2: Verify analyze**

```bash
flutter analyze lib/plugins/github_client.dart
```

Expected: `No issues found!`.

- [ ] **Step 3: Commit**

```bash
git add lib/plugins/github_client.dart
git commit -m "plugins: GithubClient — fetch registry + raw plugin source with PAT"
```

---

### Task 16: `registry.dart` — diff between installed and remote

**Files:**
- Create: `lib/plugins/registry.dart`
- Create: `test/plugins/registry_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/plugins/registry_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/plugins/registry.dart';

void main() {
  test('detects new plugins (in remote, not local)', () {
    final diff = RegistryDiff.compute(
      remote: const [
        RegistryEntry(shortName: 'echo', file: 'plugins/echo.js', version: '1.0.0', sha256: 'aa'),
        RegistryEntry(shortName: 'sc', file: 'plugins/sc.js', version: '1.0.0', sha256: 'bb'),
      ],
      installed: const [
        InstalledRecord(shortName: 'echo', version: '1.0.0', sha256: 'aa'),
      ],
    );
    expect(diff.added.map((e) => e.shortName), ['sc']);
    expect(diff.changed, isEmpty);
    expect(diff.removed, isEmpty);
    expect(diff.unchanged.map((e) => e.shortName), ['echo']);
  });

  test('detects sha256 changes (same short_name, different sha)', () {
    final diff = RegistryDiff.compute(
      remote: const [
        RegistryEntry(shortName: 'echo', file: 'plugins/echo.js', version: '1.0.1', sha256: 'cc'),
      ],
      installed: const [
        InstalledRecord(shortName: 'echo', version: '1.0.0', sha256: 'aa'),
      ],
    );
    expect(diff.changed.map((e) => e.shortName), ['echo']);
    expect(diff.added, isEmpty);
    expect(diff.removed, isEmpty);
  });

  test('detects removed plugins (in local, not in remote)', () {
    final diff = RegistryDiff.compute(
      remote: const [],
      installed: const [
        InstalledRecord(shortName: 'echo', version: '1.0.0', sha256: 'aa'),
      ],
    );
    expect(diff.removed, ['echo']);
    expect(diff.added, isEmpty);
    expect(diff.changed, isEmpty);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/plugins/registry_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/plugins/registry.dart
class RegistryEntry {
  const RegistryEntry({
    required this.shortName,
    required this.file,
    required this.version,
    required this.sha256,
    this.minAppVersion,
  });

  final String shortName;
  final String file;
  final String version;
  final String sha256;
  final String? minAppVersion;

  factory RegistryEntry.fromJson(Map<String, dynamic> json) {
    return RegistryEntry(
      shortName: json['short_name'] as String,
      file: json['file'] as String,
      version: json['version'] as String,
      sha256: json['sha256'] as String,
      minAppVersion: json['min_app_version'] as String?,
    );
  }
}

class InstalledRecord {
  const InstalledRecord({
    required this.shortName,
    required this.version,
    required this.sha256,
  });

  final String shortName;
  final String version;
  final String sha256;
}

class RegistryDiff {
  const RegistryDiff({
    required this.added,
    required this.changed,
    required this.removed,
    required this.unchanged,
  });

  /// Plugins in remote but not in local.
  final List<RegistryEntry> added;

  /// Plugins in both, with a different sha256.
  final List<RegistryEntry> changed;

  /// short_names in local but not in remote.
  final List<String> removed;

  /// Plugins in both with the same sha256.
  final List<RegistryEntry> unchanged;

  static RegistryDiff compute({
    required List<RegistryEntry> remote,
    required List<InstalledRecord> installed,
  }) {
    final byName = {for (final r in installed) r.shortName: r};
    final added = <RegistryEntry>[];
    final changed = <RegistryEntry>[];
    final unchanged = <RegistryEntry>[];

    final seenRemote = <String>{};
    for (final r in remote) {
      seenRemote.add(r.shortName);
      final local = byName[r.shortName];
      if (local == null) {
        added.add(r);
      } else if (local.sha256 != r.sha256) {
        changed.add(r);
      } else {
        unchanged.add(r);
      }
    }

    final removed = installed
        .where((i) => !seenRemote.contains(i.shortName))
        .map((i) => i.shortName)
        .toList();

    return RegistryDiff(
      added: added,
      changed: changed,
      removed: removed,
      unchanged: unchanged,
    );
  }
}
```

- [ ] **Step 4: Run tests**

```bash
flutter test test/plugins/registry_test.dart
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/registry.dart test/plugins/registry_test.dart
git commit -m "plugins: RegistryEntry + RegistryDiff — pure diff logic"
```

---

### Task 17: `loader.dart` — orchestrates registry → diff → fetch → sha256 → mount

**Files:**
- Create: `lib/plugins/loader.dart`
- Create: `test/plugins/loader_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/plugins/loader_test.dart
import 'package:crypto/crypto.dart';
import 'dart:convert';

import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/local/database.dart';
import 'package:streamload_client/plugins/github_client.dart';
import 'package:streamload_client/plugins/host/http_host.dart';
import 'package:streamload_client/plugins/host/log_host.dart';
import 'package:streamload_client/plugins/host/storage_host.dart';
import 'package:streamload_client/plugins/host_api.dart';
import 'package:streamload_client/plugins/loader.dart';
import 'package:streamload_client/plugins/runtime.dart';

class _GhMock extends Mock implements GithubClient {}

const _echoSource = '''
export const meta = {
  short_name: "echo",
  display_name: "Echo",
  version: "1.0.0",
  api_version: 1,
  capabilities: ["movie"],
};
export async function search(q) { return [{ id: "x", title: q, type: "movie", service: "echo", url: "https://example.invalid/" }]; }
export async function getSeasons() { return []; }
export async function getEpisodes() { return []; }
export async function getStreams() { return { manifest_url: "https://example.invalid/m.m3u8" }; }
''';

String _sha256OfString(String s) =>
    sha256.convert(utf8.encode(s)).toString();

void main() {
  late StreamloadDatabase db;
  late HostApi hostApi;
  late PluginRuntime runtime;
  late _GhMock gh;

  setUp(() async {
    db = StreamloadDatabase.test(NativeDatabase.memory());
    hostApi = HostApi(
      http: HttpHost(),
      storage: StorageHost(db.pluginKvDao),
      log: LogHost(sink: (_, __, ___) {}),
    );
    runtime = await PluginRuntime.create(hostApi: hostApi);
    gh = _GhMock();
  });

  tearDown(() async {
    await runtime.dispose();
    await db.close();
  });

  test('refresh: fetch registry + plugin file + sha256-verify + mount', () async {
    final hash = _sha256OfString(_echoSource);
    when(gh.getRegistry).thenAnswer((_) async => {
          'format_version': 1,
          'updated_at': '2026-05-10T00:00:00Z',
          'plugins': [
            {
              'short_name': 'echo',
              'file': 'plugins/echo.js',
              'version': '1.0.0',
              'api_version': 1,
              'sha256': hash,
              'capabilities': ['movie'],
            }
          ],
        });
    when(() => gh.getPluginSource('plugins/echo.js'))
        .thenAnswer((_) async => _echoSource);

    final loader = PluginLoader(
      github: gh,
      runtime: runtime,
      installed: db.installedPluginsDao,
    );
    final result = await loader.refresh();
    expect(result.mounted, ['echo']);
    expect(result.failed, isEmpty);

    final p = runtime.callable('echo');
    expect(p, isNotNull);
    final out = await p!.search('hello');
    expect(out.first['title'], 'hello');

    final installed = await db.installedPluginsDao.listAll();
    expect(installed.single.shortName, 'echo');
    expect(installed.single.sha256, hash);
  });

  test('refresh: sha256 mismatch → drop the file, do not mount', () async {
    when(gh.getRegistry).thenAnswer((_) async => {
          'format_version': 1,
          'updated_at': '2026-05-10T00:00:00Z',
          'plugins': [
            {
              'short_name': 'echo',
              'file': 'plugins/echo.js',
              'version': '1.0.0',
              'api_version': 1,
              'sha256': 'ff' * 32, // wrong
              'capabilities': ['movie'],
            }
          ],
        });
    when(() => gh.getPluginSource('plugins/echo.js'))
        .thenAnswer((_) async => _echoSource);

    final loader = PluginLoader(
      github: gh,
      runtime: runtime,
      installed: db.installedPluginsDao,
    );
    final result = await loader.refresh();
    expect(result.mounted, isEmpty);
    expect(result.failed, ['echo']);

    expect(runtime.callable('echo'), isNull);
    expect(await db.installedPluginsDao.listAll(), isEmpty);
  });

  test('refresh: removed-from-registry → unmount + delete row', () async {
    // Pre-seed an installed plugin.
    final hash = _sha256OfString(_echoSource);
    await db.installedPluginsDao.upsert(InstalledPluginsCompanion.insert(
      shortName: 'echo',
      version: '1.0.0',
      sha256: hash,
      filePath: 'plugins/echo.js',
    ));
    await runtime.mount(_echoSource);

    when(gh.getRegistry).thenAnswer((_) async => {
          'format_version': 1,
          'updated_at': '2026-05-10T00:00:00Z',
          'plugins': const <Map<String, dynamic>>[],
        });

    final loader = PluginLoader(
      github: gh,
      runtime: runtime,
      installed: db.installedPluginsDao,
    );
    final result = await loader.refresh();
    expect(result.removed, ['echo']);
    expect(runtime.callable('echo'), isNull);
    expect(await db.installedPluginsDao.listAll(), isEmpty);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/plugins/loader_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/plugins/loader.dart
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:drift/drift.dart';

import '../data/local/daos/installed_plugins_dao.dart';
import '../data/local/database.dart';
import 'github_client.dart';
import 'registry.dart';
import 'runtime.dart';

class RefreshResult {
  RefreshResult({
    required this.mounted,
    required this.failed,
    required this.removed,
  });

  /// short_names that were freshly mounted (added or changed).
  final List<String> mounted;

  /// short_names that failed sha256 / parse / validation.
  final List<String> failed;

  /// short_names dropped because the remote no longer lists them.
  final List<String> removed;
}

class PluginLoader {
  PluginLoader({
    required this.github,
    required this.runtime,
    required this.installed,
  });

  final GithubClient github;
  final PluginRuntime runtime;
  final InstalledPluginsDao installed;

  /// Pull the registry, diff against installed, fetch what changed, sha256-
  /// verify, mount on success / leave previous version on failure.
  Future<RefreshResult> refresh() async {
    final remoteJson = await github.getRegistry();
    final remote = (remoteJson['plugins'] as List)
        .cast<Map<String, dynamic>>()
        .map(RegistryEntry.fromJson)
        .toList();

    final installedRows = await installed.listAll();
    final installedRecords = installedRows
        .map((r) => InstalledRecord(
              shortName: r.shortName,
              version: r.version,
              sha256: r.sha256,
            ))
        .toList();

    final diff = RegistryDiff.compute(remote: remote, installed: installedRecords);

    final mounted = <String>[];
    final failed = <String>[];

    Future<void> handle(RegistryEntry entry) async {
      try {
        final source = await github.getPluginSource(entry.file);
        final actualSha = sha256.convert(utf8.encode(source)).toString();
        if (actualSha != entry.sha256) {
          throw StateError(
            'sha256 mismatch for ${entry.shortName} '
            '(registry=${entry.sha256.substring(0, 12)}…, '
            'actual=${actualSha.substring(0, 12)}…)',
          );
        }
        await runtime.mount(source);
        await installed.upsert(InstalledPluginsCompanion.insert(
          shortName: entry.shortName,
          version: entry.version,
          sha256: entry.sha256,
          filePath: entry.file,
        ));
        mounted.add(entry.shortName);
      } catch (_) {
        failed.add(entry.shortName);
      }
    }

    for (final e in diff.added) {
      await handle(e);
    }
    for (final e in diff.changed) {
      await handle(e);
    }

    final removed = <String>[];
    for (final shortName in diff.removed) {
      await runtime.unmount(shortName);
      await installed.delete(shortName);
      removed.add(shortName);
    }

    return RefreshResult(mounted: mounted, failed: failed, removed: removed);
  }
}
```

- [ ] **Step 4: Run tests**

```bash
flutter test test/plugins/loader_test.dart
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/loader.dart test/plugins/loader_test.dart
git commit -m "plugins: PluginLoader.refresh — fetch, sha256-verify, mount; atomic per plugin"
```

---

## Phase F — Riverpod providers

### Task 18: `github_pat_provider.dart`

**Files:**
- Create: `lib/state/github_pat_provider.dart`

- [ ] **Step 1: Write the provider**

```dart
// lib/state/github_pat_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/secure/secure_storage.dart';

final secureStorageProvider = Provider<SecureStorage>((_) => SecureStorage());

/// `null` while loading (first call) and when no PAT is stored.
class GithubPatNotifier extends StateNotifier<AsyncValue<String?>> {
  GithubPatNotifier(this._storage) : super(const AsyncLoading()) {
    _refresh();
  }

  final SecureStorage _storage;

  Future<void> _refresh() async {
    try {
      state = AsyncData(await _storage.githubPat());
    } catch (e, st) {
      state = AsyncError(e, st);
    }
  }

  Future<void> save(String pat) async {
    await _storage.setGithubPat(pat);
    state = AsyncData(pat);
  }

  Future<void> clear() async {
    await _storage.clearGithubPat();
    state = const AsyncData(null);
  }
}

final githubPatProvider =
    StateNotifierProvider<GithubPatNotifier, AsyncValue<String?>>((ref) {
  return GithubPatNotifier(ref.watch(secureStorageProvider));
});
```

- [ ] **Step 2: Verify analyze**

```bash
flutter analyze lib/state/github_pat_provider.dart
```

Expected: `No issues found!`.

- [ ] **Step 3: Commit**

```bash
git add lib/state/github_pat_provider.dart
git commit -m "state: githubPatProvider — reactive PAT through SecureStorage"
```

---

### Task 19: `plugin_runtime_provider.dart`

**Files:**
- Create: `lib/state/plugin_runtime_provider.dart`

- [ ] **Step 1: Write the provider**

```dart
// lib/state/plugin_runtime_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../plugins/host/http_host.dart';
import '../plugins/host/log_host.dart';
import '../plugins/host/storage_host.dart';
import '../plugins/host_api.dart';
import '../plugins/runtime.dart';
import 'database_provider.dart';

/// Long-lived PluginRuntime. Built lazily on first watch.
final pluginRuntimeProvider = FutureProvider<PluginRuntime>((ref) async {
  final db = ref.watch(databaseProvider);
  final hostApi = HostApi(
    http: HttpHost(),
    storage: StorageHost(db.pluginKvDao),
    log: LogHost(),
  );
  final runtime = await PluginRuntime.create(hostApi: hostApi);
  ref.onDispose(runtime.dispose);
  return runtime;
});
```

- [ ] **Step 2: Verify analyze**

```bash
flutter analyze lib/state/plugin_runtime_provider.dart
```

Expected: `No issues found!`.

- [ ] **Step 3: Commit**

```bash
git add lib/state/plugin_runtime_provider.dart
git commit -m "state: pluginRuntimeProvider — singleton PluginRuntime"
```

---

### Task 20: `plugins_provider.dart`

**Files:**
- Create: `lib/state/plugins_provider.dart`

- [ ] **Step 1: Write the provider**

```dart
// lib/state/plugins_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/local/database.dart';
import '../plugins/github_client.dart';
import '../plugins/loader.dart';
import 'database_provider.dart';
import 'github_pat_provider.dart';
import 'plugin_runtime_provider.dart';

/// Stream of installed plugins from drift. Empty until the first refresh.
final installedPluginsProvider =
    StreamProvider<List<InstalledPluginRow>>((ref) {
  final db = ref.watch(databaseProvider);
  return db.installedPluginsDao.watchAll();
});

/// Repo coordinates — match the streamload-plugins repo.
const _kRepoOwner = 'alfanowski';
const _kRepoName = 'streamload-plugins';

/// Builds a [PluginLoader] using the current PAT. Throws if no PAT.
final pluginLoaderProvider = FutureProvider<PluginLoader>((ref) async {
  final pat = ref.watch(githubPatProvider).value;
  if (pat == null || pat.isEmpty) {
    throw StateError('github PAT not set');
  }
  final runtime = await ref.watch(pluginRuntimeProvider.future);
  final db = ref.watch(databaseProvider);
  return PluginLoader(
    github: GithubClient(owner: _kRepoOwner, repo: _kRepoName, token: pat),
    runtime: runtime,
    installed: db.installedPluginsDao,
  );
});

/// One-shot refresh trigger; UI shows a spinner while in-flight.
class PluginRefreshController extends StateNotifier<AsyncValue<RefreshResult?>> {
  PluginRefreshController(this._ref) : super(const AsyncData(null));

  final Ref _ref;

  Future<void> refresh() async {
    state = const AsyncLoading();
    try {
      final loader = await _ref.read(pluginLoaderProvider.future);
      final result = await loader.refresh();
      state = AsyncData(result);
    } catch (e, st) {
      state = AsyncError(e, st);
    }
  }
}

final pluginRefreshControllerProvider = StateNotifierProvider<
    PluginRefreshController, AsyncValue<RefreshResult?>>((ref) {
  return PluginRefreshController(ref);
});
```

- [ ] **Step 2: Verify analyze**

```bash
flutter analyze lib/state/plugins_provider.dart
```

Expected: `No issues found!`.

- [ ] **Step 3: Commit**

```bash
git add lib/state/plugins_provider.dart
git commit -m "state: installedPluginsProvider + pluginRefreshController"
```

---

## Phase G — Onboarding page + router redirect

### Task 21: `plugin_onboarding_page.dart` — paste PAT, verify, save

**Files:**
- Create: `lib/presentation/pages/plugin_onboarding_page.dart`
- Create: `test/pages/plugin_onboarding_page_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/pages/plugin_onboarding_page_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/secure/secure_storage.dart';
import 'package:streamload_client/presentation/pages/plugin_onboarding_page.dart';
import 'package:streamload_client/presentation/theme/theme.dart';
import 'package:streamload_client/state/github_pat_provider.dart';

class _StorageMock extends Mock implements SecureStorage {}

void main() {
  testWidgets('valid PAT is saved via SecureStorage', (tester) async {
    final storage = _StorageMock();
    when(storage.githubPat).thenAnswer((_) async => null);
    when(() => storage.setGithubPat(any())).thenAnswer((_) async {});

    // Stub the verifier to return true regardless of input — we're only testing
    // that the UI calls into SecureStorage with what the user typed.
    bool Function(String) verifier(String token) {
      return (t) => t == 'github_pat_xyz';
    }

    await tester.pumpWidget(ProviderScope(
      overrides: [
        secureStorageProvider.overrideWithValue(storage),
      ],
      child: MaterialApp(
        theme: streamloadTheme(),
        home: PluginOnboardingPage(verifyPat: (t) async => t == 'github_pat_xyz'),
      ),
    ));
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('onboarding.pat')), 'github_pat_xyz',
    );
    await tester.tap(find.byKey(const Key('onboarding.submit')));
    await tester.pumpAndSettle();

    verify(() => storage.setGithubPat('github_pat_xyz')).called(1);
  });

  testWidgets('invalid PAT shows error and does not save', (tester) async {
    final storage = _StorageMock();
    when(storage.githubPat).thenAnswer((_) async => null);

    await tester.pumpWidget(ProviderScope(
      overrides: [
        secureStorageProvider.overrideWithValue(storage),
      ],
      child: MaterialApp(
        theme: streamloadTheme(),
        home: PluginOnboardingPage(verifyPat: (_) async => false),
      ),
    ));
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('onboarding.pat')), 'wrong',
    );
    await tester.tap(find.byKey(const Key('onboarding.submit')));
    await tester.pumpAndSettle();

    verifyNever(() => storage.setGithubPat(any()));
    expect(find.textContaining('non valido'), findsOneWidget);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/pages/plugin_onboarding_page_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/presentation/pages/plugin_onboarding_page.dart
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../plugins/github_client.dart';
import '../../state/github_pat_provider.dart';
import '../theme/colors.dart';
import '../theme/typography.dart';
import '../widgets/eyebrow.dart';
import '../widgets/primary_button.dart';
import '../widgets/streamload_text_field.dart';

const _kRepoOwner = 'alfanowski';
const _kRepoName = 'streamload-plugins';

typedef PatVerifier = Future<bool> Function(String token);

Future<bool> _defaultVerifier(String token) async {
  final gh = GithubClient(
    owner: _kRepoOwner,
    repo: _kRepoName,
    token: token,
    dio: Dio(BaseOptions(connectTimeout: const Duration(seconds: 10))),
  );
  return gh.verifyAccess();
}

class PluginOnboardingPage extends ConsumerStatefulWidget {
  const PluginOnboardingPage({super.key, this.verifyPat = _defaultVerifier});
  final PatVerifier verifyPat;

  @override
  ConsumerState<PluginOnboardingPage> createState() =>
      _PluginOnboardingPageState();
}

class _PluginOnboardingPageState extends ConsumerState<PluginOnboardingPage> {
  final _patCtrl = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _patCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final ok = await widget.verifyPat(_patCtrl.text.trim());
      if (!ok) {
        setState(() => _error = 'Token non valido o senza accesso al repo.');
        return;
      }
      await ref
          .read(githubPatProvider.notifier)
          .save(_patCtrl.text.trim());
      if (mounted) context.go('/home');
    } catch (e) {
      setState(() => _error = 'Verifica fallita: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(32),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Eyebrow('Pacchetto plugin'),
                const SizedBox(height: 8),
                Text(
                  'Incolla il token GitHub',
                  style: StreamloadTypography.display(fontSize: 36),
                ),
                const SizedBox(height: 12),
                Text(
                  'L\'amministratore ti ha fornito un Personal Access Token con '
                  'accesso in sola lettura al repo dei plugin. Incollalo qui sotto.',
                  style: StreamloadTypography.body(
                    fontSize: 14,
                    color: StreamloadColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 24),
                StreamloadTextField(
                  key: const Key('onboarding.pat'),
                  controller: _patCtrl,
                  label: 'GitHub PAT',
                  hint: 'github_pat_…',
                  autofocus: true,
                  obscure: true,
                ),
                if (_error != null) ...[
                  const SizedBox(height: 16),
                  Text(
                    _error!,
                    style: StreamloadTypography.body(
                      fontSize: 13,
                      color: StreamloadColors.critical,
                    ),
                  ),
                ],
                const SizedBox(height: 24),
                PrimaryButton(
                  key: const Key('onboarding.submit'),
                  label: _busy ? 'Verifica…' : 'Verifica e installa',
                  busy: _busy,
                  onPressed: _busy ? null : _submit,
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

- [ ] **Step 4: Run tests**

```bash
flutter test test/pages/plugin_onboarding_page_test.dart
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/presentation/pages/plugin_onboarding_page.dart test/pages/plugin_onboarding_page_test.dart
git commit -m "pages: PluginOnboardingPage — paste PAT, verify, save flow"
```

---

### Task 22: Wire `/onboarding/plugins` into the router

**Files:**
- Modify: `lib/router.dart`

- [ ] **Step 1: Edit `lib/router.dart`**

Replace the file with:

```dart
// lib/router.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'presentation/pages/home_page.dart';
import 'presentation/pages/login_page.dart';
import 'presentation/pages/plugin_onboarding_page.dart';
import 'presentation/pages/profile_page.dart';
import 'presentation/pages/register_page.dart';
import 'presentation/pages/settings_page.dart';
import 'state/auth_provider.dart';
import 'state/github_pat_provider.dart';

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/login',
    debugLogDiagnostics: false,
    redirect: (context, state) {
      final auth = ref.read(authProvider);
      final pat = ref.read(githubPatProvider).value;
      final loc = state.matchedLocation;
      final isAuthRoute = loc == '/login' || loc == '/register';
      final isOnboarding = loc == '/onboarding/plugins';

      if (auth is AuthLoading) return null;
      if (auth is AuthUnauthenticated || auth is AuthError) {
        return isAuthRoute ? null : '/login';
      }
      if (auth is AuthAuthenticated) {
        // Authenticated but no PAT yet → onboarding wizard.
        if ((pat == null || pat.isEmpty) && !isOnboarding) {
          return '/onboarding/plugins';
        }
        // Authenticated with PAT → leave login/register, send to home.
        if (isAuthRoute) return '/home';
        // Authenticated and at /onboarding/plugins but PAT now exists → home.
        if (isOnboarding && pat != null && pat.isNotEmpty) return '/home';
      }
      return null;
    },
    refreshListenable: _RouterRefreshNotifier(ref),
    routes: [
      GoRoute(path: '/login', builder: (_, __) => const LoginPage()),
      GoRoute(path: '/register', builder: (_, __) => const RegisterPage()),
      GoRoute(
        path: '/onboarding/plugins',
        builder: (_, __) => const PluginOnboardingPage(),
      ),
      GoRoute(path: '/home', builder: (_, __) => const HomePage()),
      GoRoute(path: '/profile', builder: (_, __) => const ProfilePage()),
      GoRoute(path: '/settings', builder: (_, __) => const SettingsPage()),
    ],
  );
});

class _RouterRefreshNotifier extends ChangeNotifier {
  _RouterRefreshNotifier(Ref ref) {
    ref.listen<AuthState>(authProvider, (_, __) => notifyListeners());
    ref.listen<AsyncValue<String?>>(
      githubPatProvider, (_, __) => notifyListeners(),
    );
  }
}
```

- [ ] **Step 2: Verify analyze**

```bash
flutter analyze lib/router.dart
```

Expected: `No issues found!`.

- [ ] **Step 3: Commit**

```bash
git add lib/router.dart
git commit -m "router: redirect to /onboarding/plugins when authenticated and no PAT"
```

---

## Phase H — Plugins page (settings sub-page)

### Task 23: `plugins_page.dart` + Settings link

**Files:**
- Create: `lib/presentation/pages/plugins_page.dart`
- Modify: `lib/presentation/pages/settings_page.dart` (add a "Plugin" navigation row)
- Modify: `lib/router.dart` (add `/plugins` route)

- [ ] **Step 1: Write the page**

```dart
// lib/presentation/pages/plugins_page.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../state/database_provider.dart';
import '../../state/github_pat_provider.dart';
import '../../state/plugins_provider.dart';
import '../theme/colors.dart';
import '../theme/typography.dart';
import '../widgets/eyebrow.dart';
import '../widgets/primary_button.dart';

class PluginsPage extends ConsumerWidget {
  const PluginsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final installed = ref.watch(installedPluginsProvider);
    final refreshState = ref.watch(pluginRefreshControllerProvider);
    final db = ref.watch(databaseProvider);

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/settings'),
        ),
        title: const Text('Plugin'),
        actions: [
          IconButton(
            tooltip: 'Aggiorna',
            icon: const Icon(Icons.refresh),
            onPressed: refreshState is AsyncLoading
                ? null
                : () => ref
                    .read(pluginRefreshControllerProvider.notifier)
                    .refresh(),
          ),
        ],
      ),
      body: installed.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Errore: $e')),
        data: (rows) {
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              const Eyebrow('Pacchetto plugin'),
              const SizedBox(height: 12),
              if (rows.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 32),
                  child: Text(
                    'Nessun plugin installato. Premi "Aggiorna" per scaricare il pacchetto.',
                    style: StreamloadTypography.body(
                      fontSize: 14,
                      color: StreamloadColors.textSecondary,
                    ),
                    textAlign: TextAlign.center,
                  ),
                )
              else
                ...rows.map((p) => Card(
                      color: StreamloadColors.surface2,
                      child: ListTile(
                        title: Text(p.shortName,
                            style: StreamloadTypography.body(
                                fontSize: 16, weight: FontWeight.w600)),
                        subtitle: Text('v${p.version}',
                            style: StreamloadTypography.mono(fontSize: 11)),
                        trailing: Switch(
                          value: p.enabled,
                          onChanged: (v) =>
                              db.installedPluginsDao.setEnabled(p.shortName, v),
                        ),
                      ),
                    )),
              const SizedBox(height: 24),
              if (refreshState is AsyncError)
                Text('Aggiornamento fallito: ${refreshState.error}',
                    style: StreamloadTypography.body(
                      fontSize: 13,
                      color: StreamloadColors.critical,
                    )),
              if (refreshState is AsyncData &&
                  (refreshState as AsyncData).value != null) ...[
                Text(
                  'Aggiornati: ${(refreshState.value as RefreshResult).mounted.length}, '
                  'falliti: ${(refreshState.value as RefreshResult).failed.length}, '
                  'rimossi: ${(refreshState.value as RefreshResult).removed.length}.',
                  style: StreamloadTypography.body(
                    fontSize: 13,
                    color: StreamloadColors.textSecondary,
                  ),
                ),
              ],
              const SizedBox(height: 24),
              PrimaryButton(
                label: 'Cambia token GitHub',
                onPressed: () async {
                  await ref.read(githubPatProvider.notifier).clear();
                  if (context.mounted) context.go('/onboarding/plugins');
                },
              ),
            ],
          );
        },
      ),
    );
  }
}
```

- [ ] **Step 2: Add a "Plugin" link inside `settings_page.dart` after the existing "Aspetto" section**

Open `lib/presentation/pages/settings_page.dart`. Find the area after the theme dropdown (the `_themeRow()` block); after the spacer that follows it, before the Save button, add:

```dart
              const SizedBox(height: 24),
              const Eyebrow('Plugin'),
              const SizedBox(height: 12),
              Card(
                color: StreamloadColors.surface2,
                child: ListTile(
                  title: const Text('Gestisci plugin installati'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => context.go('/plugins'),
                ),
              ),
```

If `context` isn't already imported via go_router in settings_page.dart, add `import 'package:go_router/go_router.dart';` at the top.

- [ ] **Step 3: Add the `/plugins` route in `lib/router.dart`**

In the `routes:` list, after the `/settings` route, add:

```dart
      GoRoute(path: '/plugins', builder: (_, __) => const PluginsPage()),
```

And add the import at the top:

```dart
import 'presentation/pages/plugins_page.dart';
```

- [ ] **Step 4: Run analyze + tests**

```bash
flutter analyze
flutter test
```

Expected: no issues, all tests pass (count grows by the page tests added in earlier tasks).

- [ ] **Step 5: Commit**

```bash
git add lib/presentation/pages/plugins_page.dart lib/presentation/pages/settings_page.dart lib/router.dart
git commit -m "pages: PluginsPage + Settings link + /plugins route"
```

---

## Phase I — Updater poll loop

### Task 24: Background poll every 30 minutes while the app is open

**Files:**
- Create: `lib/plugins/updater.dart`
- Modify: `lib/main.dart` (kick off the poll on app start)

- [ ] **Step 1: Write the updater**

```dart
// lib/plugins/updater.dart
import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../infra/logger.dart';
import '../state/plugins_provider.dart';

class PluginUpdater {
  PluginUpdater(this._ref);

  final Ref _ref;
  static final _log = Logger('plugin-updater');
  Timer? _timer;

  /// Start a foreground poll: one immediate refresh + every 30 minutes.
  void start() {
    _refresh();
    _timer ??= Timer.periodic(const Duration(minutes: 30), (_) => _refresh());
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
  }

  Future<void> _refresh() async {
    try {
      await _ref.read(pluginRefreshControllerProvider.notifier).refresh();
      _log.info('plugin refresh tick complete');
    } catch (e) {
      _log.warn('plugin refresh tick skipped: $e');
    }
  }
}

final pluginUpdaterProvider = Provider<PluginUpdater>((ref) {
  final updater = PluginUpdater(ref);
  ref.onDispose(updater.stop);
  return updater;
});
```

- [ ] **Step 2: Modify `lib/main.dart` (or `app.dart` initState) to start the updater after auth bootstrap**

Open `lib/app.dart`. Inside `_StreamloadAppState.initState()`, add the updater start AFTER the existing `bootstrap()` call:

```dart
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      await ref.read(authProvider.notifier).bootstrap();
      // Once auth is settled, start the plugin update tick. Safe to call
      // even if the user has no PAT yet — the loader will throw and the
      // updater will skip the tick gracefully.
      ref.read(pluginUpdaterProvider).start();
    });
  }
```

Add the import at the top:

```dart
import 'plugins/updater.dart';
```

- [ ] **Step 3: Verify analyze**

```bash
flutter analyze lib/plugins/updater.dart lib/app.dart
```

Expected: `No issues found!`.

- [ ] **Step 4: Commit**

```bash
git add lib/plugins/updater.dart lib/app.dart
git commit -m "plugins: PluginUpdater — refresh on app start + every 30 min"
```

---

## Phase J — End-to-end smoke

### Task 25: Manual end-to-end against the real `streamload-plugins` repo

**Files:** none (validation only).

- [ ] **Step 1: Mint a fine-grained PAT for testing**

Follow `streamload-plugins/docs/end-user-pat.md` Preferred flow. Name it `Smoke — sub-plan 4`. Expiration: 7 days. Repository access: `streamload-plugins` only. Permissions: Contents = Read-only. Copy the `github_pat_…` string.

- [ ] **Step 2: Boot the backend**

In a terminal:

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload
set -a; source .env; set +a
venv/bin/python streamload.py --api &
sleep 5
curl -s http://127.0.0.1:8000/api/health
```

Expected: `{"status":"ok","version":"0.3.0"}`.

- [ ] **Step 3: Run the Flutter app on macOS**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
flutter run -d macos
```

Expected: app boots, shows LoginPage.

- [ ] **Step 4: Login**

In the app, log in with `alfanowski` / your bootstrap admin password.

Expected: redirected to `/onboarding/plugins` (PAT keychain is empty for this fresh user state).

- [ ] **Step 5: Paste the PAT**

In the wizard, paste the `github_pat_…` from Step 1. Click **Verifica e installa**.

Expected:
- Spinner appears for ~1-3s.
- Navigates to `/home` showing "Welcome alfanowski".

- [ ] **Step 6: Open Settings → Plugin**

Click the gear icon → **Gestisci plugin installati**.

Expected: page opens, lists `echo` v1.0.0 with the toggle switch enabled.

- [ ] **Step 7: Verify echo is callable from Dart**

In a separate terminal, with the app still running:

```bash
# Connect via flutter's VM service to inspect — or just inspect drift DB:
ls /Users/alfanowski/Library/"Application Support"/com.alfanowski.streamload_client/
```

Expected: `streamload_v3.sqlite` file present.

```bash
sqlite3 ~/Library/Application\ Support/com.alfanowski.streamload_client/streamload_v3.sqlite "SELECT short_name, version, sha256 FROM installed_plugins;"
```

Expected: one row, `echo|1.0.0|<64-char hex>`.

- [ ] **Step 8: Quit the app, restart, confirm session + PAT survive**

Close the app. Re-run `flutter run -d macos`. Expected: app boots straight to `/home` (cookie + PAT both restored from Keychain).

- [ ] **Step 9: "Cambia token GitHub" flow**

Settings → Plugin → **Cambia token GitHub**. Expected: app navigates to `/onboarding/plugins`. Paste the same PAT, submit, lands back on `/home`.

- [ ] **Step 10: Stop the backend**

```bash
pkill -9 -f granian 2>/dev/null
```

- [ ] **Step 11: Revoke the smoke PAT**

GitHub → Settings → Developer settings → Personal access tokens → Fine-grained → revoke `Smoke — sub-plan 4`.

- [ ] **Step 12: Final test suite green**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
flutter test
```

Expected: all tests pass.

---

## Plan complete

After Task 25 you have:

- A QuickJS sandbox embedded in the Flutter client, scoped to a strict `host.*` API surface.
- A typed `Plugin` Dart wrapper that calls into the four contract functions (`search`, `getSeasons`, `getEpisodes`, `getStreams`).
- A `PluginLoader` that pulls `registry.json` from the private `streamload-plugins` repo with a per-user PAT, sha256-verifies each plugin file, and atomically mounts/swaps it.
- A first-run onboarding wizard that hides the GitHub plumbing behind a single "paste your token" screen.
- A Settings → Plugin page where the operator's user can see installed plugins, toggle them on/off, force a refresh, or rotate the PAT.
- A 30-minute background poll that keeps plugins current without user interaction.
- The drift `installed_plugins` and `plugin_kv` tables wired to their first real consumers.

What's deliberately NOT here (and why):

- **HLS playback / media_kit / local proxy** — sub-plan #5 will consume `Plugin.getStreams()` to drive playback; this plan only delivers the `Plugin` wrapper and verifies it can call into JS.
- **Catalog browse / search / title / watch UI** — sub-plan #6 wires the rest.
- **Auto-update for the app binary itself** — sub-plan #6 (Sparkle/auto_updater).
- **WebAuthn passkey** — sub-plan #6.
