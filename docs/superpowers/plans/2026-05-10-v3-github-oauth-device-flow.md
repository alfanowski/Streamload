# v3 GitHub OAuth Device Flow + Browse-Only Degradation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "paste a fine-grained PAT" onboarding (Plan #4) with a one-click GitHub OAuth Device Flow login, AND make plugin access optional — users without read access to the private `streamload-plugins` repo still launch the app and can browse the TMDB catalog (no streaming affordances).

**Architecture:** A `GithubOAuth` client implements the device flow against `github.com/login/device/code` + `/login/oauth/access_token`. The onboarding page becomes a single "Accedi con GitHub" button that opens the verification URI in the system browser, displays a 6-character user code, and polls for the access token in the background. The token is stored via the existing `SecureStorage` (Keychain or prefs fallback). After the token is saved, `PluginLoader.refresh()` runs — but its result is now classified into `PluginAccess.{unknown,available,noAccess,networkError}` and exposed via a new `pluginAccessProvider`. The UI conditionally hides streaming affordances (Watch button, plugins settings list) when access is `noAccess`. The router redirect no longer blocks at `/onboarding/plugins` based on plugin presence — only on token absence.

**Tech Stack:** Flutter 3.41+, Dart 3.11+, dio, riverpod 2.6, freezed 2.5, url_launcher 6.x, flutter_clipboard (or services.dart Clipboard).

---

## Source spec

This plan refines **Plan #4** (`docs/superpowers/plans/2026-05-10-v3-plugin-runtime.md`) and parts of **sub-plan 6a** (`docs/superpowers/plans/2026-05-10-v3-catalog-browse-ui.md`):

- **Plan #4 §6** introduced the PAT-paste onboarding. This plan replaces that with OAuth device flow.
- **Plan #4 PluginLoader** treated registry-fetch failure as a hard error. This plan adds a "noAccess" classification (HTTP 404 from `/repos/{owner}/{repo}/contents/registry.json` = user is not a collaborator) that the loader returns instead of throwing.
- **Sub-plan 6a TitlePage** unconditionally renders the Watch button. This plan gates it on `pluginAccessProvider`.

The terminal state of this plan is: a freshly-installed app, after backend login, takes the user to a "Login with GitHub" screen. Click → app shows a code like `ABCD-1234` and a button "Apri pagina GitHub" that launches `https://github.com/login/device` in Safari. User pastes the code, authorizes the OAuth App, returns to the app. The app saves the access token and tries to fetch the plugin registry. If 200 → plugins mount, full streaming UI. If 404 → toast "Pacchetto plugin non disponibile" + browse-only mode (Watch button hidden, settings shows "Richiedi accesso"). Either way the user lands on `/home` and sees the catalog.

## OAuth App config (operator-side, already done)

| Field | Value |
|---|---|
| OAuth App name | Streamload |
| Client ID | `Ov23liocgW9mW4skr2Fs` |
| Client secret | n/a (device flow doesn't need one) |
| Device flow enabled | ✅ |
| Required scopes when requesting | `repo` (so user's session can read private collaborator repos) |
| Per-user setup | Operator invites each user as Read collaborator on `alfanowski/streamload-plugins` via repo Settings → Collaborators |

The `Client ID` is hardcoded in the app — it's public by design in device flow.

## File structure

### New files

| Path | Created in | Purpose |
|---|---|---|
| `lib/plugins/github_oauth.dart` | T2 | `GithubOAuth` client — device-code request + token poll loop |
| `lib/state/plugin_access_provider.dart` | T6 | exposes `PluginAccess` enum derived from loader result + a refresh-on-token-change side effect |
| `docs/OAUTH_SETUP.md` | T11 | operator runbook for OAuth App + collaborator invites |
| `test/plugins/github_oauth_test.dart` | T2 | mock dio, exercise device flow end-to-end |
| `test/state/plugin_access_provider_test.dart` | T6 | available / noAccess / networkError transitions |

### Renamed files

| From | To | Change |
|---|---|---|
| `lib/state/github_pat_provider.dart` | `lib/state/github_token_provider.dart` | rename `githubPatProvider` → `githubTokenProvider`, same SecureStorage backing |
| `lib/data/secure/secure_storage.dart` `_kGithubPat` | `_kGithubToken` | key migration; on read, also check old key for backwards compat with users who have a saved PAT |

### Modified files

| Path | Modified in | Change |
|---|---|---|
| `pubspec.yaml` | T1 | add `url_launcher: ^6.3.1` |
| `lib/plugins/loader.dart` | T5 | classify registry fetch into RefreshOutcome (success / noAccess / networkError) instead of throwing |
| `lib/presentation/pages/plugin_onboarding_page.dart` | T7 | full rewrite — single login button + code display + browser launch + polling + done |
| `lib/router.dart` | T8 | redirect logic: missing token → /onboarding/github (rename), token present → /home regardless of plugin access |
| `lib/presentation/pages/title_page.dart` | T9 | hide Watch button when `pluginAccessProvider != available` |
| `lib/presentation/pages/plugins_page.dart` | T10 | when access is noAccess: render "Richiedi accesso" empty state instead of plugin list |
| `lib/state/plugins_provider.dart` | T5 | `pluginRefreshControllerProvider` exposes `RefreshOutcome` not just success/failure |

---

## Phase A — Dependencies + OAuth client

### Task 1: Add `url_launcher` dep

**Files:**
- Modify: `pubspec.yaml`

- [ ] **Step 1: Add to dependencies (after `cached_network_image:`)**

```yaml
  url_launcher: ^6.3.1
```

- [ ] **Step 2: `flutter pub get` + verify suite still green**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
flutter pub get
flutter test 2>&1 | tail -3
```

- [ ] **Step 3: Commit**

```bash
git add pubspec.yaml pubspec.lock macos/Flutter/GeneratedPluginRegistrant.swift macos/Podfile.lock
git commit -m "deps: url_launcher for opening GitHub device verification URI"
```

---

### Task 2: `GithubOAuth` device flow client + tests

**Files:**
- Create: `lib/plugins/github_oauth.dart`
- Create: `test/plugins/github_oauth_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/plugins/github_oauth_test.dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/plugins/github_oauth.dart';

class _DioMock extends Mock implements Dio {}

Response<Map<String, dynamic>> _resp(Map<String, dynamic> body, {int status = 200}) =>
    Response<Map<String, dynamic>>(
      requestOptions: RequestOptions(path: ''),
      data: body,
      statusCode: status,
    );

void main() {
  setUpAll(() {
    registerFallbackValue(RequestOptions(path: ''));
    registerFallbackValue(Options());
  });

  late _DioMock dio;
  late GithubOAuth oauth;

  setUp(() {
    dio = _DioMock();
    oauth = GithubOAuth(clientId: 'TEST_CLIENT_ID', dio: dio);
  });

  group('requestDeviceCode', () {
    test('parses successful response into DeviceCodeRequest', () async {
      when(() => dio.post<Map<String, dynamic>>(
            'https://github.com/login/device/code',
            data: any(named: 'data'),
            options: any(named: 'options'),
          )).thenAnswer((_) async => _resp({
            'device_code': 'dev-abc',
            'user_code': 'ABCD-1234',
            'verification_uri': 'https://github.com/login/device',
            'expires_in': 900,
            'interval': 5,
          }));

      final result = await oauth.requestDeviceCode();
      expect(result.deviceCode, 'dev-abc');
      expect(result.userCode, 'ABCD-1234');
      expect(result.verificationUri, 'https://github.com/login/device');
      expect(result.expiresIn, const Duration(seconds: 900));
      expect(result.pollInterval, const Duration(seconds: 5));
    });

    test('throws on non-2xx', () async {
      when(() => dio.post<Map<String, dynamic>>(
            any(),
            data: any(named: 'data'),
            options: any(named: 'options'),
          )).thenAnswer((_) async => _resp({'error': 'invalid_client'}, status: 400));
      expect(oauth.requestDeviceCode, throwsA(isA<StateError>()));
    });
  });

  group('pollForToken', () {
    test('returns token when GitHub returns 200 with access_token', () async {
      when(() => dio.post<Map<String, dynamic>>(
            'https://github.com/login/oauth/access_token',
            data: any(named: 'data'),
            options: any(named: 'options'),
          )).thenAnswer((_) async => _resp({
            'access_token': 'ghu_xyz789',
            'token_type': 'bearer',
            'scope': 'repo',
          }));

      final token = await oauth.pollForToken(
        deviceCode: 'dev-abc',
        interval: const Duration(milliseconds: 10),
        timeout: const Duration(seconds: 1),
      );
      expect(token, 'ghu_xyz789');
    });

    test('keeps polling while GitHub responds with authorization_pending', () async {
      var calls = 0;
      when(() => dio.post<Map<String, dynamic>>(
            any(),
            data: any(named: 'data'),
            options: any(named: 'options'),
          )).thenAnswer((_) async {
        calls++;
        if (calls < 3) {
          return _resp({'error': 'authorization_pending'});
        }
        return _resp({'access_token': 'ghu_late', 'token_type': 'bearer', 'scope': 'repo'});
      });

      final token = await oauth.pollForToken(
        deviceCode: 'dev-abc',
        interval: const Duration(milliseconds: 5),
        timeout: const Duration(seconds: 1),
      );
      expect(token, 'ghu_late');
      expect(calls, 3);
    });

    test('respects slow_down by extending the interval', () async {
      var calls = 0;
      when(() => dio.post<Map<String, dynamic>>(
            any(),
            data: any(named: 'data'),
            options: any(named: 'options'),
          )).thenAnswer((_) async {
        calls++;
        if (calls == 1) return _resp({'error': 'slow_down'});
        return _resp({'access_token': 't', 'token_type': 'bearer', 'scope': 'repo'});
      });
      // Should still complete within timeout even with slow_down.
      final token = await oauth.pollForToken(
        deviceCode: 'dev-abc',
        interval: const Duration(milliseconds: 5),
        timeout: const Duration(seconds: 2),
      );
      expect(token, 't');
    });

    test('throws DeviceFlowDenied when user denies', () async {
      when(() => dio.post<Map<String, dynamic>>(
            any(),
            data: any(named: 'data'),
            options: any(named: 'options'),
          )).thenAnswer((_) async => _resp({'error': 'access_denied'}));
      expect(
        () => oauth.pollForToken(
          deviceCode: 'd', interval: const Duration(milliseconds: 5),
          timeout: const Duration(milliseconds: 100),
        ),
        throwsA(isA<DeviceFlowDenied>()),
      );
    });

    test('throws DeviceFlowExpired on expired_token', () async {
      when(() => dio.post<Map<String, dynamic>>(
            any(),
            data: any(named: 'data'),
            options: any(named: 'options'),
          )).thenAnswer((_) async => _resp({'error': 'expired_token'}));
      expect(
        () => oauth.pollForToken(
          deviceCode: 'd', interval: const Duration(milliseconds: 5),
          timeout: const Duration(milliseconds: 100),
        ),
        throwsA(isA<DeviceFlowExpired>()),
      );
    });

    test('throws TimeoutException when own timeout fires before user authorizes', () async {
      when(() => dio.post<Map<String, dynamic>>(
            any(),
            data: any(named: 'data'),
            options: any(named: 'options'),
          )).thenAnswer((_) async => _resp({'error': 'authorization_pending'}));
      expect(
        () => oauth.pollForToken(
          deviceCode: 'd', interval: const Duration(milliseconds: 5),
          timeout: const Duration(milliseconds: 50),
        ),
        throwsA(isA<DeviceFlowExpired>()),
      );
    });
  });
}
```

- [ ] **Step 2: Run tests, expect failure**

- [ ] **Step 3: Implement**

```dart
// lib/plugins/github_oauth.dart
import 'dart:async';

import 'package:dio/dio.dart';

class DeviceCodeRequest {
  const DeviceCodeRequest({
    required this.deviceCode,
    required this.userCode,
    required this.verificationUri,
    required this.expiresIn,
    required this.pollInterval,
  });

  final String deviceCode;
  final String userCode;
  final String verificationUri;
  final Duration expiresIn;
  final Duration pollInterval;
}

class DeviceFlowDenied implements Exception {
  const DeviceFlowDenied();
  @override
  String toString() => 'GitHub device flow: user denied authorization';
}

class DeviceFlowExpired implements Exception {
  const DeviceFlowExpired();
  @override
  String toString() => 'GitHub device flow: code expired before authorization';
}

/// GitHub OAuth Device Flow client. The Client ID is public by design; the
/// app embeds it as a const. No client_secret is needed for device flow.
///
/// Flow:
///   1. POST /login/device/code → get { device_code, user_code, verification_uri, ... }
///   2. Show user_code + open verification_uri in the browser
///   3. Poll POST /login/oauth/access_token until 200 (token), 400/access_denied,
///      or our timeout
class GithubOAuth {
  GithubOAuth({required this.clientId, Dio? dio})
      : _dio = dio ??
            Dio(BaseOptions(
              connectTimeout: const Duration(seconds: 10),
              receiveTimeout: const Duration(seconds: 15),
              headers: {'Accept': 'application/json'},
              validateStatus: (_) => true,
            ));

  final String clientId;
  final Dio _dio;

  /// Step 1: ask GitHub for a device code.
  Future<DeviceCodeRequest> requestDeviceCode({String scope = 'repo'}) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      'https://github.com/login/device/code',
      data: {'client_id': clientId, 'scope': scope},
      options: Options(contentType: Headers.formUrlEncodedContentType),
    );
    if (resp.statusCode != 200 || resp.data == null) {
      throw StateError('github device/code → ${resp.statusCode}: ${resp.data}');
    }
    final body = resp.data!;
    return DeviceCodeRequest(
      deviceCode: body['device_code'] as String,
      userCode: body['user_code'] as String,
      verificationUri: body['verification_uri'] as String,
      expiresIn: Duration(seconds: (body['expires_in'] as num).toInt()),
      pollInterval: Duration(seconds: (body['interval'] as num).toInt()),
    );
  }

  /// Step 2: poll until the user authorizes (or denies / times out).
  ///
  /// Errors raised:
  /// - [DeviceFlowDenied] on `access_denied`
  /// - [DeviceFlowExpired] on `expired_token` OR when `timeout` elapses
  /// - [StateError] on any other unexpected response
  Future<String> pollForToken({
    required String deviceCode,
    required Duration interval,
    required Duration timeout,
  }) async {
    final deadline = DateTime.now().add(timeout);
    var currentInterval = interval;
    while (DateTime.now().isBefore(deadline)) {
      final resp = await _dio.post<Map<String, dynamic>>(
        'https://github.com/login/oauth/access_token',
        data: {
          'client_id': clientId,
          'device_code': deviceCode,
          'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
        },
        options: Options(contentType: Headers.formUrlEncodedContentType),
      );
      final body = resp.data ?? const <String, dynamic>{};
      if (body['access_token'] is String) {
        return body['access_token'] as String;
      }
      final err = body['error'] as String?;
      switch (err) {
        case 'authorization_pending':
          break; // keep polling at currentInterval
        case 'slow_down':
          currentInterval = currentInterval + const Duration(seconds: 5);
          break;
        case 'access_denied':
          throw const DeviceFlowDenied();
        case 'expired_token':
          throw const DeviceFlowExpired();
        default:
          throw StateError('github access_token → $err / $body');
      }
      await Future<void>.delayed(currentInterval);
    }
    throw const DeviceFlowExpired();
  }
}
```

- [ ] **Step 4: Run tests, expect 7 pass**

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/github_oauth.dart test/plugins/github_oauth_test.dart
git commit -m "plugins: GithubOAuth device flow client (request_codes + poll)"
```

---

## Phase B — Token storage rename + access state

### Task 3: Rename `githubPatProvider` → `githubTokenProvider`

**Files:**
- Move: `lib/state/github_pat_provider.dart` → `lib/state/github_token_provider.dart`
- Modify: `lib/data/secure/secure_storage.dart` — rename `_kGithubPat` → `_kGithubToken`, add backwards-compat read of old key
- Modify: all callers (router, plugins_page, plugins_provider, plugin_onboarding_page if not yet rewritten by Task 7, tests)

- [ ] **Step 1: Update `secure_storage.dart`**

```dart
  static const _kGithubToken = 'streamload.github_token';
  static const _kLegacyGithubPat = 'streamload.github_pat';

  /// Reads the saved token. For backwards compat with users who onboarded
  /// via the PAT flow before OAuth landed, falls back to the legacy
  /// 'streamload.github_pat' key if the new key is empty.
  Future<String?> githubToken() async {
    final fresh = await _backend.read(_kGithubToken);
    if (fresh != null) return fresh;
    return _backend.read(_kLegacyGithubPat);
  }
  Future<void> setGithubToken(String value) =>
      _backend.write(_kGithubToken, value);
  Future<void> clearGithubToken() async {
    await _backend.delete(_kGithubToken);
    await _backend.delete(_kLegacyGithubPat);
  }
```

Remove the old `githubPat()` / `setGithubPat()` / `clearGithubPat()` methods.

- [ ] **Step 2: Move + rename the provider**

```bash
git mv lib/state/github_pat_provider.dart lib/state/github_token_provider.dart
```

Inside, rename:
- `GithubPatNotifier` → `GithubTokenNotifier`
- `githubPatProvider` → `githubTokenProvider`
- `_storage.githubPat()` → `_storage.githubToken()`
- `_storage.setGithubPat(pat)` → `_storage.setGithubToken(token)`
- `_storage.clearGithubPat()` → `_storage.clearGithubToken()`

- [ ] **Step 3: Find every caller and rename. Fix imports.**

```bash
grep -rln "githubPatProvider\|github_pat_provider\.dart\|_storage\.githubPat\|setGithubPat\|clearGithubPat" lib/ test/
```

For every match:
- Import: `state/github_pat_provider.dart` → `state/github_token_provider.dart`
- Reference: `githubPatProvider` → `githubTokenProvider`

(Leave the `plugin_onboarding_page.dart` rewrite for Task 7 — for now just update the existing references so the build stays green.)

- [ ] **Step 4: Run full suite, expect green**

```bash
flutter test 2>&1 | tail -3
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "state: rename githubPatProvider → githubTokenProvider (storage backwards-compatible)"
```

---

### Task 4: `PluginAccess` enum + `RefreshOutcome` model

**Files:**
- Modify: `lib/plugins/loader.dart` — add `RefreshOutcome` enum + adjust return type
- Modify: `lib/state/plugins_provider.dart` — `pluginRefreshControllerProvider` exposes `AsyncValue<RefreshOutcome>` instead of `RefreshResult`

- [ ] **Step 1: Update `loader.dart`**

Add at the top of the file:

```dart
enum RefreshOutcome { success, noAccess, networkError, notRun }

class RefreshSummary {
  RefreshSummary({
    required this.outcome,
    required this.mounted,
    required this.failed,
    required this.removed,
  });

  final RefreshOutcome outcome;
  final List<String> mounted;
  final List<String> failed;
  final List<String> removed;

  factory RefreshSummary.notRun() =>
      RefreshSummary(outcome: RefreshOutcome.notRun, mounted: const [], failed: const [], removed: const []);
}
```

Change `PluginLoader.refresh()` return type from `Future<RefreshResult>` to `Future<RefreshSummary>`. Wrap the existing body with classification:

```dart
Future<RefreshSummary> refresh() async {
  final Map<String, dynamic> remoteJson;
  try {
    remoteJson = await github.getRegistry();
  } on DioException catch (e) {
    if (e.response?.statusCode == 404 || e.response?.statusCode == 403) {
      _log.info('plugin registry → ${e.response?.statusCode}; user has no access');
      return RefreshSummary(
        outcome: RefreshOutcome.noAccess,
        mounted: const [], failed: const [], removed: const [],
      );
    }
    _log.warn('plugin registry network error: $e');
    return RefreshSummary(
      outcome: RefreshOutcome.networkError,
      mounted: const [], failed: const [], removed: const [],
    );
  } catch (e) {
    _log.warn('plugin registry unexpected error: $e');
    return RefreshSummary(
      outcome: RefreshOutcome.networkError,
      mounted: const [], failed: const [], removed: const [],
    );
  }
  // ... existing logic builds the lists, then return:
  return RefreshSummary(
    outcome: RefreshOutcome.success,
    mounted: mounted, failed: failed, removed: removed,
  );
}
```

> **Note:** the existing body uses `await github.getRegistry()` inline. Refactor so it's wrapped in the try/catch above and the rest of the function continues only on success.

> Also: `_log` doesn't currently exist on the loader. Add a `final _log = Logger('plugin.loader');` field if it isn't already there from earlier fixes.

Delete the old `RefreshResult` class — its data lives on `RefreshSummary` now.

- [ ] **Step 2: Update `plugins_provider.dart`**

```dart
class PluginRefreshController extends StateNotifier<AsyncValue<RefreshSummary>> {
  PluginRefreshController(this._ref)
      : super(AsyncData(RefreshSummary.notRun()));

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
```

- [ ] **Step 3: Update existing loader_test cases — expect `RefreshSummary` not `RefreshResult`. Add new tests for the 404 → noAccess and network error paths.**

```dart
test('refresh: 404 from getRegistry → outcome noAccess', () async {
  when(gh.getRegistry).thenThrow(DioException(
    requestOptions: RequestOptions(path: ''),
    response: Response(requestOptions: RequestOptions(path: ''), statusCode: 404),
  ));
  final loader = PluginLoader(
    github: gh, runtime: runtime, installed: db.installedPluginsDao,
  );
  final result = await loader.refresh();
  expect(result.outcome, RefreshOutcome.noAccess);
});

test('refresh: connection refused → outcome networkError', () async {
  when(gh.getRegistry).thenThrow(DioException(
    requestOptions: RequestOptions(path: ''),
    type: DioExceptionType.connectionError,
  ));
  final loader = PluginLoader(
    github: gh, runtime: runtime, installed: db.installedPluginsDao,
  );
  final result = await loader.refresh();
  expect(result.outcome, RefreshOutcome.networkError);
});
```

- [ ] **Step 4: Run full suite, expect green**

- [ ] **Step 5: Commit**

```bash
git add lib/plugins/loader.dart lib/state/plugins_provider.dart test/plugins/loader_test.dart
git commit -m "plugins: classify registry-fetch failure as noAccess vs networkError instead of throwing"
```

---

### Task 5: `pluginAccessProvider`

**Files:**
- Create: `lib/state/plugin_access_provider.dart`
- Create: `test/state/plugin_access_provider_test.dart`

- [ ] **Step 1: Write the failing test**

```dart
// test/state/plugin_access_provider_test.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/plugins/loader.dart';
import 'package:streamload_client/state/plugin_access_provider.dart';
import 'package:streamload_client/state/plugins_provider.dart';

void main() {
  test('initial → unknown', () {
    final c = ProviderContainer();
    addTearDown(c.dispose);
    expect(c.read(pluginAccessProvider), PluginAccess.unknown);
  });

  test('after AsyncData(success) → available', () {
    final c = ProviderContainer(overrides: [
      pluginRefreshControllerProvider.overrideWith(
        (ref) => _StubRefreshNotifier(RefreshSummary(
          outcome: RefreshOutcome.success,
          mounted: const ['echo'], failed: const [], removed: const [],
        )),
      ),
    ]);
    addTearDown(c.dispose);
    expect(c.read(pluginAccessProvider), PluginAccess.available);
  });

  test('after AsyncData(noAccess) → noAccess', () {
    final c = ProviderContainer(overrides: [
      pluginRefreshControllerProvider.overrideWith(
        (ref) => _StubRefreshNotifier(RefreshSummary(
          outcome: RefreshOutcome.noAccess,
          mounted: const [], failed: const [], removed: const [],
        )),
      ),
    ]);
    addTearDown(c.dispose);
    expect(c.read(pluginAccessProvider), PluginAccess.noAccess);
  });

  test('after AsyncData(networkError) → networkError', () {
    final c = ProviderContainer(overrides: [
      pluginRefreshControllerProvider.overrideWith(
        (ref) => _StubRefreshNotifier(RefreshSummary(
          outcome: RefreshOutcome.networkError,
          mounted: const [], failed: const [], removed: const [],
        )),
      ),
    ]);
    addTearDown(c.dispose);
    expect(c.read(pluginAccessProvider), PluginAccess.networkError);
  });
}

class _StubRefreshNotifier extends PluginRefreshController {
  _StubRefreshNotifier(RefreshSummary value) : super(_FakeRef()) {
    state = AsyncData(value);
  }
}

class _FakeRef extends Fake implements Ref {}
```

- [ ] **Step 2: Implement**

```dart
// lib/state/plugin_access_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../plugins/loader.dart';
import 'plugins_provider.dart';

enum PluginAccess { unknown, available, noAccess, networkError }

/// Derived from the most recent [pluginRefreshControllerProvider] state.
/// `unknown` while loading or before any refresh has run.
final pluginAccessProvider = Provider<PluginAccess>((ref) {
  final state = ref.watch(pluginRefreshControllerProvider);
  return state.maybeWhen(
    data: (summary) {
      switch (summary.outcome) {
        case RefreshOutcome.success:
          return PluginAccess.available;
        case RefreshOutcome.noAccess:
          return PluginAccess.noAccess;
        case RefreshOutcome.networkError:
          return PluginAccess.networkError;
        case RefreshOutcome.notRun:
          return PluginAccess.unknown;
      }
    },
    orElse: () => PluginAccess.unknown,
  );
});
```

- [ ] **Step 3: Run, expect 4 pass**

- [ ] **Step 4: Commit**

```bash
git add lib/state/plugin_access_provider.dart test/state/plugin_access_provider_test.dart
git commit -m "state: pluginAccessProvider — derive PluginAccess from loader outcome"
```

---

## Phase C — UI rewrite

### Task 6: Constant for the OAuth Client ID + helper provider

**Files:**
- Create: `lib/plugins/github_oauth_config.dart`

- [ ] **Step 1: Create the config file**

```dart
// lib/plugins/github_oauth_config.dart
//
// GitHub OAuth App configured by the operator.
// The Client ID is public by design in device flow.

const String kGithubOAuthClientId = 'Ov23liocgW9mW4skr2Fs';
```

- [ ] **Step 2: Commit (no test — pure config)**

```bash
git add lib/plugins/github_oauth_config.dart
git commit -m "plugins: hardcode GitHub OAuth App Client ID"
```

---

### Task 7: Rewrite `plugin_onboarding_page.dart` for device flow

**Files:**
- Modify: `lib/presentation/pages/plugin_onboarding_page.dart` (full rewrite)
- Modify: `test/pages/plugin_onboarding_page_test.dart` (rewrite tests for the new UI states)

The new page has 3 states:
1. **idle**: shows "Accedi con GitHub" button. Click → transitions to awaitingUser.
2. **awaitingUser**: shows the user_code prominently, "Apri pagina GitHub" button (uses `url_launcher`), "Copia codice" button. Background timer polls for the token; on success → save token via `githubTokenNotifier.save()` → kick off `pluginRefreshControllerProvider.refresh()` → `context.go('/home')`. On denial/timeout → show error in the same screen.
3. **error**: shows the error + "Riprova" button to go back to idle.

Note: after saving the token, we navigate to `/home` regardless of whether the user has plugin access or not. The home will render correctly in browse-only mode if access is `noAccess`.

- [ ] **Step 1: Write the failing tests for the new UI**

Tests should cover:
- idle → tap "Accedi con GitHub" → mocked `requestDeviceCode` called → user_code shown
- awaitingUser → polling returns token → token saved + navigation to /home
- awaitingUser → polling throws DeviceFlowDenied → error message shown, "Riprova" button visible
- "Copia codice" copies user_code to clipboard

Use a `OAuthFactory` typedef so the test can inject a fake oauth client:

```dart
typedef OAuthFactory = GithubOAuth Function();
```

Page constructor accepts `OAuthFactory? oauthFactory` defaulting to `() => GithubOAuth(clientId: kGithubOAuthClientId)`.

(Adapt the existing onboarding test file rather than starting from scratch — it has the riverpod scaffolding ready.)

- [ ] **Step 2: Implement**

The full implementation is large — sketch:

```dart
// lib/presentation/pages/plugin_onboarding_page.dart
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../plugins/github_oauth.dart';
import '../../plugins/github_oauth_config.dart';
import '../../state/github_token_provider.dart';
import '../../state/plugins_provider.dart';
import '../theme/colors.dart';
import '../theme/typography.dart';
import '../widgets/eyebrow.dart';
import '../widgets/primary_button.dart';

typedef OAuthFactory = GithubOAuth Function();

GithubOAuth _defaultFactory() =>
    GithubOAuth(clientId: kGithubOAuthClientId);

enum _OnboardingState { idle, awaitingUser, polling, error }

class PluginOnboardingPage extends ConsumerStatefulWidget {
  const PluginOnboardingPage({super.key, this.oauthFactory = _defaultFactory});
  final OAuthFactory oauthFactory;

  @override
  ConsumerState<PluginOnboardingPage> createState() =>
      _PluginOnboardingPageState();
}

class _PluginOnboardingPageState extends ConsumerState<PluginOnboardingPage> {
  _OnboardingState _state = _OnboardingState.idle;
  DeviceCodeRequest? _device;
  String? _error;

  Future<void> _start() async {
    setState(() {
      _state = _OnboardingState.awaitingUser;
      _error = null;
    });
    final oauth = widget.oauthFactory();
    try {
      final dev = await oauth.requestDeviceCode();
      if (!mounted) return;
      setState(() => _device = dev);
      // Open the verification page in the browser to nudge the user.
      await launchUrl(Uri.parse(dev.verificationUri),
          mode: LaunchMode.externalApplication);
      // Begin polling.
      final token = await oauth.pollForToken(
        deviceCode: dev.deviceCode,
        interval: dev.pollInterval,
        timeout: dev.expiresIn,
      );
      if (!mounted) return;
      // Save the token.
      await ref.read(githubTokenProvider.notifier).save(token);
      // Kick off a registry refresh — but don't block the UI on its result.
      // Whether it succeeds (full mode) or 404s (browse-only), the user lands
      // on /home and the UI conditions on pluginAccessProvider.
      // ignore: unawaited_futures
      ref.read(pluginRefreshControllerProvider.notifier).refresh();
      if (mounted) context.go('/home');
    } on DeviceFlowDenied {
      _setError('Hai annullato l\'accesso. Riprova quando vuoi.');
    } on DeviceFlowExpired {
      _setError('Il codice è scaduto. Riprova.');
    } catch (e) {
      _setError('Errore: $e');
    }
  }

  void _setError(String msg) {
    if (!mounted) return;
    setState(() {
      _state = _OnboardingState.error;
      _error = msg;
    });
  }

  Future<void> _copyCode() async {
    if (_device == null) return;
    await Clipboard.setData(ClipboardData(text: _device!.userCode));
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Codice copiato')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: switch (_state) {
              _OnboardingState.idle => _IdleView(onStart: _start),
              _OnboardingState.awaitingUser ||
              _OnboardingState.polling =>
                _AwaitingView(
                  device: _device,
                  onCopy: _copyCode,
                ),
              _OnboardingState.error =>
                _ErrorView(message: _error ?? '', onRetry: () {
                  setState(() {
                    _state = _OnboardingState.idle;
                    _error = null;
                    _device = null;
                  });
                }),
            },
          ),
        ),
      ),
    );
  }
}

class _IdleView extends StatelessWidget {
  const _IdleView({required this.onStart});
  final VoidCallback onStart;
  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        const Eyebrow('Pacchetto plugin'),
        const SizedBox(height: 8),
        Text('Accedi con GitHub',
            style: StreamloadTypography.display(fontSize: 36)),
        const SizedBox(height: 12),
        Text(
          "Streamload usa GitHub per autenticarti e — se sei stato invitato — "
          "scaricare il pacchetto plugin. Se non hai invito, "
          "potrai comunque sfogliare il catalogo.",
          style: StreamloadTypography.body(
              fontSize: 14, color: StreamloadColors.textSecondary),
        ),
        const SizedBox(height: 24),
        PrimaryButton(
          key: const Key('onboarding.github_login'),
          label: 'Accedi con GitHub',
          onPressed: onStart,
        ),
      ],
    );
  }
}

class _AwaitingView extends StatelessWidget {
  const _AwaitingView({required this.device, required this.onCopy});
  final DeviceCodeRequest? device;
  final VoidCallback onCopy;
  @override
  Widget build(BuildContext context) {
    if (device == null) {
      return const Center(child: CircularProgressIndicator());
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        const Eyebrow('Autorizzazione'),
        const SizedBox(height: 8),
        Text('Inserisci il codice',
            style: StreamloadTypography.display(fontSize: 32)),
        const SizedBox(height: 12),
        Text(
          'Apri ${device!.verificationUri} (dovrebbe già essersi aperto) '
          'e incolla questo codice:',
          style: StreamloadTypography.body(fontSize: 14),
        ),
        const SizedBox(height: 24),
        Container(
          padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 16),
          decoration: BoxDecoration(
            color: StreamloadColors.surface2,
            borderRadius: BorderRadius.circular(8),
          ),
          alignment: Alignment.center,
          child: Text(
            device!.userCode,
            style: StreamloadTypography.mono(fontSize: 32, letterSpacing: 4),
          ),
        ),
        const SizedBox(height: 16),
        OutlinedButton.icon(
          onPressed: onCopy,
          icon: const Icon(Icons.copy, size: 16),
          label: const Text('Copia codice'),
        ),
        const SizedBox(height: 24),
        const Center(child: CircularProgressIndicator()),
        const SizedBox(height: 8),
        Text('In attesa di autorizzazione…',
            textAlign: TextAlign.center,
            style: StreamloadTypography.body(
                fontSize: 12, color: StreamloadColors.textSecondary)),
      ],
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        const Eyebrow('Errore'),
        const SizedBox(height: 8),
        Text(message,
            style: StreamloadTypography.body(
                fontSize: 14, color: StreamloadColors.critical)),
        const SizedBox(height: 24),
        PrimaryButton(label: 'Riprova', onPressed: onRetry),
      ],
    );
  }
}
```

- [ ] **Step 3: Run + commit**

```bash
git add lib/presentation/pages/plugin_onboarding_page.dart test/pages/plugin_onboarding_page_test.dart
git commit -m "pages: rewrite onboarding for GitHub device flow (single-button login)"
```

---

### Task 8: Router cleanup — rename route + drop plugin-access gate

**Files:**
- Modify: `lib/router.dart`

- [ ] **Step 1: Rename `/onboarding/plugins` → `/onboarding/github`** (the route is now about GitHub auth, not specifically plugin install). Update the route definition AND the redirect logic. The redirect still kicks unauthenticated-without-token to `/onboarding/github`, but does NOT care about plugin-access state.

```dart
final isOnboarding = loc == '/onboarding/github';
// ...
if (auth is AuthAuthenticated) {
  if ((token == null || token.isEmpty) && !isOnboarding) {
    return '/onboarding/github';
  }
  if (isAuthRoute) return '/home';
  if (isOnboarding && token != null && token.isNotEmpty) return '/home';
}
```

(`token` replaces `pat` everywhere in the redirect callback; rename via Find+Replace.)

- [ ] **Step 2: Run, expect green**

- [ ] **Step 3: Commit**

```bash
git add lib/router.dart
git commit -m "router: rename /onboarding/plugins → /onboarding/github (token-only gate)"
```

---

### Task 9: Hide Watch button on TitlePage when no plugin access

**Files:**
- Modify: `lib/presentation/pages/title_page.dart`

- [ ] **Step 1: Make `_TitleMovieBody` and `_TitleTvBody` consumers; gate the Watch button behind `pluginAccessProvider == available`**

In `_TitleMovieBody`:

```dart
final access = ref.watch(pluginAccessProvider);
// ...
if (access == PluginAccess.available)
  PrimaryButton(
    label: 'Guarda',
    onPressed: () => context.go(
      '/watch/$tmdbId?media_type=$mediaType',
    ),
  ),
```

In `_TitleTvBody`, gate the per-episode tap behavior:

```dart
final access = ref.watch(pluginAccessProvider);
// inside episode ListTile:
onTap: access == PluginAccess.available
    ? () => context.go(
        '/watch/${widget.tmdbId}?media_type=tv'
        '&season=${e.season}&episode=${e.episode}',
      )
    : null,
```

For TV, also fade the episode tile when `access != available` — wrap in `Opacity(opacity: 0.5, child: ...)`.

- [ ] **Step 2: Add 1 test for movie variant covering both states**

```dart
testWidgets('Watch button hidden when access is noAccess', (tester) async {
  // ... pump TitlePage with pluginAccessProvider overridden to noAccess
  expect(find.text('Guarda'), findsNothing);
});

testWidgets('Watch button visible when access is available', (tester) async {
  // ... pump with override = available
  expect(find.text('Guarda'), findsOneWidget);
});
```

- [ ] **Step 3: Run + commit**

```bash
git add lib/presentation/pages/title_page.dart test/pages/title_page_test.dart
git commit -m "pages: TitlePage hides Watch button when pluginAccess != available"
```

---

### Task 10: PluginsPage shows "Richiedi accesso" when noAccess

**Files:**
- Modify: `lib/presentation/pages/plugins_page.dart`

- [ ] **Step 1: When `pluginAccessProvider == noAccess`, render an empty-state card explaining the situation:**

```dart
final access = ref.watch(pluginAccessProvider);
if (access == PluginAccess.noAccess) {
  return Scaffold(
    appBar: AppBar(title: const Text('Plugin')),
    body: Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.lock_outline, size: 48),
            const SizedBox(height: 16),
            Text('Pacchetto plugin non disponibile',
                style: StreamloadTypography.display(fontSize: 24)),
            const SizedBox(height: 12),
            Text(
              "Il tuo account GitHub non ha accesso al pacchetto plugin "
              "di Streamload. Senza il pacchetto puoi sfogliare il "
              "catalogo, ma non avviare la riproduzione. Contatta "
              "l'amministratore per chiedere l'invito.",
              textAlign: TextAlign.center,
              style: StreamloadTypography.body(
                  fontSize: 14, color: StreamloadColors.textSecondary),
            ),
            const SizedBox(height: 24),
            OutlinedButton(
              onPressed: () async {
                await ref.read(githubTokenProvider.notifier).clear();
                if (context.mounted) context.go('/onboarding/github');
              },
              child: const Text('Cambia account GitHub'),
            ),
          ],
        ),
      ),
    ),
  );
}
// ... rest of the existing implementation when access is available
```

For `PluginAccess.networkError`, render a similar empty state but with a "Riprova" button calling `pluginRefreshControllerProvider.refresh()`.

- [ ] **Step 2: Manual smoke (no test — covered by widget test scaffolding for now)**

- [ ] **Step 3: Commit**

```bash
git add lib/presentation/pages/plugins_page.dart
git commit -m "pages: PluginsPage shows lock empty-state when access is noAccess/networkError"
```

---

## Phase D — Documentation

### Task 11: Operator runbook for OAuth + collaborator setup

**Files:**
- Create: `docs/OAUTH_SETUP.md`

- [ ] **Step 1: Write the runbook**

```markdown
# GitHub OAuth + Plugin Access Setup

This document describes how to:
1. Create the OAuth App on github.com.
2. Invite a new user to access the plugin pack.
3. Revoke a user's access.

## 1. OAuth App (one-time)

1. https://github.com/settings/developers → **New OAuth App**.
2. Application name: `Streamload`.
3. Homepage URL: `https://streamload.alfanowski.it` (placeholder; not used).
4. Authorization callback URL: `http://localhost` (required field; not used in device flow).
5. Tick **Enable Device Flow**.
6. **Register application**.
7. Copy the Client ID and paste it into `lib/plugins/github_oauth_config.dart`. The Client ID is public by design.

## 2. Inviting a user

1. Open `https://github.com/alfanowski/streamload-plugins/settings/access`.
2. **Add people** → username or email of the new user.
3. Role: **Read**.
4. Confirm.
5. The user receives an email invitation. Once they accept, they can log in via the app and the registry will be available to them.

## 3. Revoking access

1. Same page as above → click the `x` next to their entry → **Remove**.
2. Their next plugin refresh (every 30 min while the app is open) will return 404; the app will silently switch to browse-only mode and show a toast informing them.

## 4. Rotating the OAuth App

If the Client ID needs to be rotated (compromise, account migration, etc.):

1. Create a new OAuth App with a different name.
2. Update `lib/plugins/github_oauth_config.dart` with the new Client ID.
3. Build and ship a new app version.
4. Old tokens issued under the previous OAuth App remain valid until users re-login or revoke them.
```

- [ ] **Step 2: Commit**

```bash
git add docs/OAUTH_SETUP.md
git commit -m "docs: operator runbook for GitHub OAuth + collaborator invites"
```

---

## Acceptance criteria

- 195+ tests pass (~15 new across the plan).
- `flutter analyze` clean.
- Backend login → onboarding screen with one **"Accedi con GitHub"** button.
- Click → user_code shown + GitHub device URL opens in Safari.
- After authorization, user lands on `/home` regardless of plugin access.
- Title page Watch button is visible if and only if `pluginAccess == available`.
- Plugins settings page shows a lock empty-state when access is `noAccess`.
- A user without an invitation can fully browse home / library / search / title pages.

## Out of scope

- Toast on access loss mid-session (decided as future polish — silent degrade is acceptable for MVP).
- Session refresh / token rotation (GitHub OAuth tokens are non-expiring by default).
- Logout that clears the GitHub token (today's logout only clears the session cookie — it's a separate logout).
- GitHub Apps with fine-grained permissions (would replace OAuth Apps; not needed at 10-user scale).
- Anything related to sub-plan 6b (watch + sync) — that lands in its own plan.
