# v3 Client Foundation (Flutter) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a working Flutter macOS app shell that authenticates against the v0.3.0 backend, persists session + user settings, and ships a typed ApiClient covering every reduced-backend endpoint. Real catalog UI / playback / plugins arrive in sub-plans #4-#6.

**Architecture:** Clean-architecture-ish layered Flutter app with `presentation/`, `domain/`, `data/{remote,local,secure}/`, `state/` (riverpod), and `infra/` boundaries. Local SQLite via drift covers every v3 schema table (most are dormant until later sub-plans). Dio with a persistent cookie jar carries the backend session. Google Fonts loads Fraunces + Geist on-demand. go_router gates routes on auth state.

**Tech Stack:** Flutter 3.24+, Dart 3.5+, riverpod 2.5+, drift 2.18+, dio 5.7+, go_router 14+, freezed 2.5+, flutter_secure_storage 9+, google_fonts.

---

## Source spec

This plan implements **Sub-plan #3** from `docs/superpowers/specs/2026-05-09-streamload-v3-design.md` §17. Schema mirror per §9.2. Theme tokens per §11 of the v2 web frontend spec carried over.

The terminal state of this plan is: an unsigned macOS `.app` that boots, shows a login screen, registers/authenticates against `http://127.0.0.1:8000`, persists the cookie across restarts, and lets the user round-trip `/api/settings`. Sub-plans #4-6 add plugins, playback, and full UI.

## File structure

### Repo root files (Tasks 1, 3, 32)

| Path | Responsibility |
|---|---|
| `pubspec.yaml` | Pinned dependencies + asset declarations. |
| `analysis_options.yaml` | Lints (start from `flutter_lints` package recommended set). |
| `.gitignore` | Flutter-standard + macOS clutter. |
| `README.md` | One-paragraph project intro + dev quickstart. |
| `.github/workflows/test.yml` | CI: `flutter test` on push + PR. |
| `macos/Runner/DebugProfile.entitlements` | App Sandbox: outgoing network + Keychain access. |
| `macos/Runner/Release.entitlements` | Same. |

### `lib/` (Tasks 4-31)

```
lib/
├── main.dart                                  Task 27
├── app.dart                                   Task 27
├── router.dart                                Task 26
├── infra/
│   ├── env.dart                               Task 14
│   └── logger.dart                            Task 14
├── presentation/
│   ├── theme/
│   │   ├── colors.dart                        Task 4
│   │   ├── typography.dart                    Task 5
│   │   └── theme.dart                         Task 6
│   ├── widgets/
│   │   ├── eyebrow.dart                       Task 7
│   │   ├── primary_button.dart                Task 7
│   │   └── streamload_text_field.dart         Task 7
│   └── pages/
│       ├── login_page.dart                    Task 28
│       ├── register_page.dart                 Task 29
│       ├── home_page.dart                     Task 30
│       ├── profile_page.dart                  Task 30
│       └── settings_page.dart                 Task 31
├── domain/
│   └── models/
│       ├── user.dart                          Task 17
│       ├── settings.dart                      Task 17
│       └── catalog_item.dart                  Task 17
├── data/
│   ├── secure/
│   │   └── secure_storage.dart                Task 13
│   ├── local/
│   │   ├── database.dart                      Task 9 + 10
│   │   ├── schema/
│   │   │   ├── catalog_items.dart             Task 8
│   │   │   ├── tv_episodes.dart               Task 8
│   │   │   ├── catalog_sources.dart           Task 8
│   │   │   ├── watch_progress.dart            Task 8
│   │   │   ├── favorites.dart                 Task 8
│   │   │   ├── watchlist.dart                 Task 8
│   │   │   ├── user_settings.dart             Task 8
│   │   │   ├── outbox.dart                    Task 8
│   │   │   ├── installed_plugins.dart         Task 8
│   │   │   └── plugin_kv.dart                 Task 8
│   │   └── daos/
│   │       ├── catalog_dao.dart               Task 11
│   │       └── user_settings_dao.dart         Task 11
│   └── remote/
│       ├── api_exception.dart                 Task 15
│       ├── api_client.dart                    Task 16
│       └── endpoints/
│           ├── auth_api.dart                  Task 18
│           ├── catalog_api.dart               Task 19
│           ├── collections_api.dart           Task 19
│           ├── episodes_api.dart              Task 19
│           ├── library_api.dart               Task 19
│           ├── search_api.dart                Task 20
│           ├── intro_api.dart                 Task 20
│           ├── next_up_api.dart               Task 20
│           ├── progress_api.dart              Task 21
│           ├── favorites_api.dart             Task 21
│           ├── watchlist_api.dart             Task 21
│           ├── settings_api.dart              Task 21
│           ├── events_api.dart                Task 21
│           └── admin_api.dart                 Task 22
└── state/
    ├── database_provider.dart                 Task 12
    ├── api_client_provider.dart               Task 23
    ├── auth_provider.dart                     Task 24
    └── settings_provider.dart                 Task 25
```

### `test/` (interleaved with implementation tasks)

```
test/
├── theme_test.dart                            Task 6
├── widgets/
│   ├── eyebrow_test.dart                      Task 7
│   └── primary_button_test.dart               Task 7
├── data/
│   ├── secure_storage_test.dart               Task 13
│   ├── database_test.dart                     Task 10
│   ├── catalog_dao_test.dart                  Task 11
│   ├── user_settings_dao_test.dart            Task 11
│   └── remote/
│       ├── api_exception_test.dart            Task 15
│       ├── api_client_test.dart               Task 16
│       ├── auth_api_test.dart                 Task 18
│       ├── catalog_api_test.dart              Task 19
│       ├── search_api_test.dart               Task 20
│       ├── progress_api_test.dart             Task 21
│       ├── favorites_api_test.dart            Task 21
│       └── settings_api_test.dart             Task 21
├── state/
│   ├── auth_provider_test.dart                Task 24
│   └── settings_provider_test.dart            Task 25
└── pages/
    ├── login_page_test.dart                   Task 28
    ├── register_page_test.dart                Task 29
    └── settings_page_test.dart                Task 31
```

---

## Phase A — Project bootstrap

### Task 1: Scaffold the Flutter project

**Files:**
- Create: `/Users/alfanowski/Desktop/Projects/Streamload-Client/` (whole new tree)
- Modify: `/Users/alfanowski/Desktop/Projects/Streamload-Client/pubspec.yaml` (replaced in Task 2)

- [ ] **Step 1: Run flutter create with macOS-only target**

```bash
cd /Users/alfanowski/Desktop/Projects/
flutter create \
  --platforms=macos \
  --org com.alfanowski \
  --description "Streamload v3 desktop client (Flutter)" \
  --project-name streamload_client \
  Streamload-Client
```

Expected: `flutter create` prints "All done!" and creates the directory with a sample counter app.

- [ ] **Step 2: Verify the scaffold builds and runs `flutter test`**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
flutter pub get
flutter test
```

Expected: pub get succeeds, default widget test passes (1 passed).

- [ ] **Step 3: Drop the placeholder counter app**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
rm lib/main.dart
rm test/widget_test.dart
```

`lib/main.dart` and `test/widget_test.dart` will be replaced by Tasks 27 and the per-component test tasks.

- [ ] **Step 4: Init git on `main`, commit the bare scaffold**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
git init -b main
git add -A
git commit -m "chore: initial flutter create scaffold (macOS target)"
```

Expected: commit lands.

---

### Task 2: Pin dependencies in `pubspec.yaml`

**Files:**
- Modify: `pubspec.yaml`

- [ ] **Step 1: Replace the entire `pubspec.yaml`**

```yaml
name: streamload_client
description: "Streamload v3 desktop client (Flutter)"
publish_to: 'none'
version: 0.3.0+1

environment:
  sdk: ^3.5.0
  flutter: ">=3.24.0"

dependencies:
  flutter:
    sdk: flutter
  cupertino_icons: ^1.0.8

  # State management
  flutter_riverpod: ^2.5.1

  # Routing
  go_router: ^14.2.7

  # Local DB
  drift: ^2.18.0
  drift_flutter: ^0.2.1
  sqlite3_flutter_libs: ^0.5.24

  # Secure storage / preferences
  flutter_secure_storage: ^9.2.2
  shared_preferences: ^2.3.2
  path_provider: ^2.1.4

  # HTTP
  dio: ^5.7.0
  dio_cookie_manager: ^3.2.0
  cookie_jar: ^4.0.8

  # Immutable models
  freezed_annotation: ^2.4.4
  json_annotation: ^4.9.0

  # UI
  google_fonts: ^6.2.1
  lucide_icons: ^0.257.0

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^4.0.0
  freezed: ^2.5.7
  json_serializable: ^6.8.0
  drift_dev: ^2.18.0
  build_runner: ^2.4.13
  mocktail: ^1.0.4

flutter:
  uses-material-design: true
```

- [ ] **Step 2: Resolve the new pin set**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
flutter pub get
```

Expected: resolves without conflicts. If a transitive resolution fails, run `flutter pub upgrade --major-versions` and re-pin to the resolved versions.

- [ ] **Step 3: Commit**

```bash
git add pubspec.yaml pubspec.lock
git commit -m "deps: pin v3 client foundation stack (riverpod/drift/dio/freezed/google_fonts)"
```

---

### Task 3: Create the GitHub repo + push the scaffold

**Files:** none (remote operation only).

- [ ] **Step 1: Verify gh CLI is logged in as alfanowski**

```bash
gh auth status 2>&1 | head -3
```

Expected: contains `Logged in to github.com account alfanowski`.

- [ ] **Step 2: Create the public repo**

```bash
gh repo create alfanowski/Streamload-Client \
  --public \
  --description "Streamload v3 desktop client (Flutter)" \
  --disable-wiki
```

Expected: prints `https://github.com/alfanowski/Streamload-Client`.

- [ ] **Step 3: Add the remote and push**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
git remote add origin https://github.com/alfanowski/Streamload-Client.git
git push -u origin main
```

Expected: branch tracks origin/main, push succeeds.

- [ ] **Step 4: Verify visibility**

```bash
gh repo view alfanowski/Streamload-Client --json visibility,name | python3 -m json.tool
```

Expected: `"visibility": "PUBLIC"`.

---

## Phase B — Theme + reusable widgets

### Task 4: Color tokens

**Files:**
- Create: `lib/presentation/theme/colors.dart`

- [ ] **Step 1: Write the color tokens**

```dart
// Cinematic Editorial color tokens, ported from v2 SvelteKit app.css.
// Surfaces are warm-tinted near-blacks; text is warm off-white; accent is amber.

import 'package:flutter/material.dart';

class StreamloadColors {
  StreamloadColors._();

  // Backgrounds
  static const Color bg = Color(0xFF08090A);
  static const Color bgElevated = Color(0xFF0E0F11);
  static const Color surface1 = Color(0xFF131316);
  static const Color surface2 = Color(0xFF1B1B1F);
  static const Color surface3 = Color(0xFF25252B);

  // Text — warm off-white with explicit alpha for tiers
  static const Color textPrimary = Color(0xFFF5F2EC);
  static const Color textSecondary = Color(0xA8F5F2EC); // 66% alpha
  static const Color textTertiary = Color(0x6BF5F2EC); // 42% alpha
  static const Color textMuted = Color(0x47F5F2EC); // 28% alpha

  // Accents
  static const Color accent = Color(0xFFD4A574);
  static const Color accentHover = Color(0xFFE2B888);
  static const Color gold = Color(0xFFF4D17C);
  static const Color critical = Color(0xFFF26B5E);
  static const Color success = Color(0xFF7CC089);

  // Borders / separators
  static const Color border = Color(0x14F5F2EC); // ~8% alpha
  static const Color borderStrong = Color(0x29F5F2EC); // ~16% alpha
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
flutter analyze lib/presentation/theme/colors.dart
```

Expected: `No issues found!`.

- [ ] **Step 3: Commit**

```bash
git add lib/presentation/theme/colors.dart
git commit -m "theme: Cinematic Editorial color tokens"
```

---

### Task 5: Typography (Fraunces serif + Geist body + Geist Mono)

**Files:**
- Create: `lib/presentation/theme/typography.dart`

- [ ] **Step 1: Write the typography**

```dart
// Cinematic Editorial typography, ported from v2 SvelteKit.
// Display: Fraunces (variable serif). Body: Geist. Mono: Geist Mono.
// All loaded on-demand via google_fonts (no asset bundling needed).

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'colors.dart';

class StreamloadTypography {
  StreamloadTypography._();

  /// Editorial display titles. Use sparingly: hero, page titles, section headers.
  static TextStyle display({
    double fontSize = 48,
    FontWeight weight = FontWeight.w400,
    bool italic = true,
    Color color = StreamloadColors.textPrimary,
  }) {
    return GoogleFonts.fraunces(
      fontSize: fontSize,
      fontWeight: weight,
      fontStyle: italic ? FontStyle.italic : FontStyle.normal,
      letterSpacing: -0.025 * fontSize,
      height: 1.0,
      color: color,
    );
  }

  /// Body text — Geist.
  static TextStyle body({
    double fontSize = 14,
    FontWeight weight = FontWeight.w400,
    Color color = StreamloadColors.textPrimary,
    double height = 1.5,
  }) {
    return GoogleFonts.geist(
      fontSize: fontSize,
      fontWeight: weight,
      letterSpacing: -0.005 * fontSize,
      height: height,
      color: color,
    );
  }

  /// Monospace — used for technical labels (eyebrow text, version strings, IDs).
  static TextStyle mono({
    double fontSize = 11,
    FontWeight weight = FontWeight.w400,
    Color color = StreamloadColors.textTertiary,
    double letterSpacing = 0.18,
  }) {
    return GoogleFonts.geistMono(
      fontSize: fontSize,
      fontWeight: weight,
      letterSpacing: letterSpacing,
      color: color,
    );
  }

  /// Bundle a complete TextTheme.
  static TextTheme textTheme() {
    return TextTheme(
      displayLarge: display(fontSize: 64),
      displayMedium: display(fontSize: 48),
      displaySmall: display(fontSize: 36),
      headlineLarge: display(fontSize: 32),
      headlineMedium: display(fontSize: 24),
      headlineSmall: display(fontSize: 20),
      titleLarge: body(fontSize: 18, weight: FontWeight.w500),
      titleMedium: body(fontSize: 16, weight: FontWeight.w500),
      titleSmall: body(fontSize: 14, weight: FontWeight.w500),
      bodyLarge: body(fontSize: 16),
      bodyMedium: body(fontSize: 14),
      bodySmall: body(fontSize: 12, color: StreamloadColors.textSecondary),
      labelLarge: body(fontSize: 14, weight: FontWeight.w500),
      labelMedium: mono(fontSize: 12),
      labelSmall: mono(fontSize: 10),
    );
  }
}
```

- [ ] **Step 2: Verify analyze**

```bash
flutter analyze lib/presentation/theme/typography.dart
```

Expected: `No issues found!`.

- [ ] **Step 3: Commit**

```bash
git add lib/presentation/theme/typography.dart
git commit -m "theme: Fraunces/Geist/Geist Mono typography via google_fonts"
```

---

### Task 6: ThemeData + first widget test

**Files:**
- Create: `lib/presentation/theme/theme.dart`
- Create: `test/theme_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/theme_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/presentation/theme/theme.dart';
import 'package:streamload_client/presentation/theme/colors.dart';

void main() {
  group('streamloadTheme()', () {
    final theme = streamloadTheme();

    test('uses dark Cinematic Editorial colors', () {
      expect(theme.brightness, Brightness.dark);
      expect(theme.scaffoldBackgroundColor, StreamloadColors.bg);
      expect(theme.colorScheme.surface, StreamloadColors.surface1);
      expect(theme.colorScheme.primary, StreamloadColors.accent);
      expect(theme.colorScheme.error, StreamloadColors.critical);
    });

    test('text theme is non-empty and primary text is warm off-white', () {
      expect(theme.textTheme.bodyMedium, isNotNull);
      expect(theme.textTheme.bodyMedium!.color, StreamloadColors.textPrimary);
    });
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/theme_test.dart
```

Expected: fails with `Could not resolve 'streamload_client/presentation/theme/theme.dart'` (or similar — the file doesn't exist yet).

- [ ] **Step 3: Implement the theme**

```dart
// lib/presentation/theme/theme.dart
//
// Cinematic Editorial ThemeData. Single entry point: streamloadTheme().

import 'package:flutter/material.dart';

import 'colors.dart';
import 'typography.dart';

ThemeData streamloadTheme() {
  const colorScheme = ColorScheme.dark(
    surface: StreamloadColors.surface1,
    onSurface: StreamloadColors.textPrimary,
    primary: StreamloadColors.accent,
    onPrimary: Color(0xFF1A1308),
    secondary: StreamloadColors.gold,
    onSecondary: Color(0xFF1A1308),
    error: StreamloadColors.critical,
    onError: Colors.white,
    surfaceContainerHighest: StreamloadColors.surface3,
    outline: StreamloadColors.borderStrong,
    outlineVariant: StreamloadColors.border,
  );

  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    scaffoldBackgroundColor: StreamloadColors.bg,
    canvasColor: StreamloadColors.bg,
    colorScheme: colorScheme,
    textTheme: StreamloadTypography.textTheme(),
    splashFactory: NoSplash.splashFactory,
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: StreamloadColors.surface2,
      hoverColor: StreamloadColors.surface3,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: StreamloadColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: StreamloadColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: StreamloadColors.accent, width: 1.5),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: StreamloadColors.critical),
      ),
      labelStyle: StreamloadTypography.mono(
        fontSize: 11,
        color: StreamloadColors.textTertiary,
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: ButtonStyle(
        backgroundColor: WidgetStatePropertyAll(StreamloadColors.accent),
        foregroundColor: const WidgetStatePropertyAll(Color(0xFF1A1308)),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
        ),
        padding: const WidgetStatePropertyAll(
          EdgeInsets.symmetric(horizontal: 24, vertical: 14),
        ),
        textStyle: WidgetStatePropertyAll(
          StreamloadTypography.body(
            fontSize: 14,
            weight: FontWeight.w600,
            color: const Color(0xFF1A1308),
          ),
        ),
      ),
    ),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: StreamloadColors.surface2,
      contentTextStyle: TextStyle(color: StreamloadColors.textPrimary),
    ),
  );
}
```

- [ ] **Step 4: Run, expect pass**

```bash
flutter test test/theme_test.dart
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/presentation/theme/theme.dart test/theme_test.dart
git commit -m "theme: streamloadTheme() Material 3 ThemeData with Cinematic Editorial tokens"
```

---

### Task 7: Reusable widgets — Eyebrow, PrimaryButton, StreamloadTextField

**Files:**
- Create: `lib/presentation/widgets/eyebrow.dart`
- Create: `lib/presentation/widgets/primary_button.dart`
- Create: `lib/presentation/widgets/streamload_text_field.dart`
- Create: `test/widgets/eyebrow_test.dart`
- Create: `test/widgets/primary_button_test.dart`

- [ ] **Step 1: Write failing tests FIRST**

```dart
// test/widgets/eyebrow_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/presentation/theme/theme.dart';
import 'package:streamload_client/presentation/widgets/eyebrow.dart';

void main() {
  testWidgets('renders the label uppercased and visible', (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: streamloadTheme(),
      home: const Scaffold(body: Eyebrow('in primo piano')),
    ));
    expect(find.text('IN PRIMO PIANO'), findsOneWidget);
  });
}
```

```dart
// test/widgets/primary_button_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/presentation/theme/theme.dart';
import 'package:streamload_client/presentation/widgets/primary_button.dart';

void main() {
  testWidgets('fires onPressed when enabled', (tester) async {
    var pressed = 0;
    await tester.pumpWidget(MaterialApp(
      theme: streamloadTheme(),
      home: Scaffold(
        body: PrimaryButton(
          label: 'Accedi',
          onPressed: () => pressed++,
        ),
      ),
    ));
    await tester.tap(find.text('Accedi'));
    expect(pressed, 1);
  });

  testWidgets('shows progress and disables tap when busy', (tester) async {
    var pressed = 0;
    await tester.pumpWidget(MaterialApp(
      theme: streamloadTheme(),
      home: Scaffold(
        body: PrimaryButton(
          label: 'Accedi',
          busy: true,
          onPressed: () => pressed++,
        ),
      ),
    ));
    await tester.tap(find.byType(PrimaryButton));
    expect(pressed, 0);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });
}
```

- [ ] **Step 2: Run, expect failures**

```bash
flutter test test/widgets/
```

Expected: both tests fail with import errors.

- [ ] **Step 3: Implement Eyebrow**

```dart
// lib/presentation/widgets/eyebrow.dart
import 'package:flutter/material.dart';

import '../theme/colors.dart';
import '../theme/typography.dart';

/// Small uppercase mono label used as a section/page eyebrow.
class Eyebrow extends StatelessWidget {
  const Eyebrow(this.text, {super.key, this.color});

  final String text;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return Text(
      text.toUpperCase(),
      style: StreamloadTypography.mono(
        fontSize: 11,
        color: color ?? StreamloadColors.textTertiary,
      ),
    );
  }
}
```

- [ ] **Step 4: Implement PrimaryButton**

```dart
// lib/presentation/widgets/primary_button.dart
import 'package:flutter/material.dart';

import '../theme/colors.dart';

class PrimaryButton extends StatelessWidget {
  const PrimaryButton({
    super.key,
    required this.label,
    this.onPressed,
    this.busy = false,
    this.icon,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool busy;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final disabled = busy || onPressed == null;
    return FilledButton(
      onPressed: disabled ? null : onPressed,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (busy) ...[
            const SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: Color(0xFF1A1308),
              ),
            ),
            const SizedBox(width: 10),
          ] else if (icon != null) ...[
            Icon(icon, size: 18, color: const Color(0xFF1A1308)),
            const SizedBox(width: 8),
          ],
          Text(label),
        ],
      ),
    );
  }
}
```

- [ ] **Step 5: Implement StreamloadTextField**

```dart
// lib/presentation/widgets/streamload_text_field.dart
import 'package:flutter/material.dart';

class StreamloadTextField extends StatelessWidget {
  const StreamloadTextField({
    super.key,
    required this.controller,
    required this.label,
    this.hint,
    this.obscure = false,
    this.autofocus = false,
    this.keyboardType,
    this.onSubmitted,
    this.validator,
  });

  final TextEditingController controller;
  final String label;
  final String? hint;
  final bool obscure;
  final bool autofocus;
  final TextInputType? keyboardType;
  final ValueChanged<String>? onSubmitted;
  final FormFieldValidator<String>? validator;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: controller,
      obscureText: obscure,
      autofocus: autofocus,
      keyboardType: keyboardType,
      onFieldSubmitted: onSubmitted,
      validator: validator,
      decoration: InputDecoration(
        labelText: label.toUpperCase(),
        hintText: hint,
      ),
    );
  }
}
```

- [ ] **Step 6: Run, expect pass**

```bash
flutter test test/widgets/
```

Expected: 3 tests pass.

- [ ] **Step 7: Commit**

```bash
git add lib/presentation/widgets/ test/widgets/
git commit -m "widgets: Eyebrow, PrimaryButton, StreamloadTextField + tests"
```

---

## Phase C — Drift schema + database

### Task 8: Drift table definitions (10 tables)

**Files:**
- Create: `lib/data/local/schema/catalog_items.dart`
- Create: `lib/data/local/schema/tv_episodes.dart`
- Create: `lib/data/local/schema/catalog_sources.dart`
- Create: `lib/data/local/schema/watch_progress.dart`
- Create: `lib/data/local/schema/favorites.dart`
- Create: `lib/data/local/schema/watchlist.dart`
- Create: `lib/data/local/schema/user_settings.dart`
- Create: `lib/data/local/schema/outbox.dart`
- Create: `lib/data/local/schema/installed_plugins.dart`
- Create: `lib/data/local/schema/plugin_kv.dart`

- [ ] **Step 1: Write `catalog_items.dart`**

```dart
import 'package:drift/drift.dart';

@DataClassName('CatalogItemRow')
class CatalogItems extends Table {
  IntColumn get tmdbId => integer()();
  TextColumn get mediaType => text()();
  TextColumn get title => text()();
  TextColumn get originalTitle => text().nullable()();
  IntColumn get year => integer().nullable()();
  TextColumn get posterUrl => text().nullable()();
  TextColumn get backdropUrl => text().nullable()();
  TextColumn get overview => text().nullable()();
  RealColumn get rating => real().nullable()();
  IntColumn get runtimeMinutes => integer().nullable()();
  IntColumn get seasonsCount => integer().nullable()();
  TextColumn get genresJson => text().withDefault(const Constant('[]'))();
  DateTimeColumn get metadataFetchedAt => dateTime().withDefault(currentDateAndTime)();

  @override
  Set<Column> get primaryKey => {tmdbId, mediaType};
}
```

- [ ] **Step 2: Write `tv_episodes.dart`**

```dart
import 'package:drift/drift.dart';

@DataClassName('TvEpisodeRow')
class TvEpisodes extends Table {
  IntColumn get tmdbId => integer()();
  TextColumn get mediaType => text().withDefault(const Constant('tv'))();
  IntColumn get seasonNumber => integer()();
  IntColumn get episodeNumber => integer()();
  TextColumn get title => text().nullable()();
  TextColumn get overview => text().nullable()();
  DateTimeColumn get airDate => dateTime().nullable()();
  IntColumn get runtimeMinutes => integer().nullable()();
  TextColumn get stillUrl => text().nullable()();

  @override
  Set<Column> get primaryKey => {tmdbId, mediaType, seasonNumber, episodeNumber};
}
```

- [ ] **Step 3: Write `catalog_sources.dart` (LOCAL ONLY — never sent to server)**

```dart
import 'package:drift/drift.dart';

/// LOCAL ONLY. The plugin runtime in sub-plan #4 fills this. Never synced
/// to the operator's backend (radioactive — would link the operator to
/// upstream pirate URLs).
@DataClassName('CatalogSourceRow')
class CatalogSources extends Table {
  IntColumn get tmdbId => integer()();
  TextColumn get mediaType => text()();
  TextColumn get pluginShortName => text()();
  TextColumn get serviceUrl => text()();
  TextColumn get serviceMediaId => text()();
  IntColumn get qualityMaxHeight => integer().nullable()();
  TextColumn get audioLangsJson => text().withDefault(const Constant('[]'))();
  TextColumn get subsLangsJson => text().withDefault(const Constant('[]'))();
  IntColumn get successCount => integer().withDefault(const Constant(0))();
  IntColumn get failureCount => integer().withDefault(const Constant(0))();
  DateTimeColumn get lastVerifiedAt => dateTime().withDefault(currentDateAndTime)();

  @override
  Set<Column> get primaryKey => {tmdbId, mediaType, pluginShortName};
}
```

- [ ] **Step 4: Write `watch_progress.dart`**

```dart
import 'package:drift/drift.dart';

@DataClassName('WatchProgressRow')
class WatchProgress extends Table {
  IntColumn get tmdbId => integer()();
  TextColumn get mediaType => text()();
  IntColumn get seasonNumber => integer().withDefault(const Constant(0))();
  IntColumn get episodeNumber => integer().withDefault(const Constant(0))();
  IntColumn get positionSeconds => integer()();
  IntColumn get durationSeconds => integer()();
  BoolColumn get completed => boolean().withDefault(const Constant(false))();
  DateTimeColumn get updatedAt => dateTime().withDefault(currentDateAndTime)();

  @override
  Set<Column> get primaryKey => {tmdbId, mediaType, seasonNumber, episodeNumber};
}
```

- [ ] **Step 5: Write `favorites.dart`**

```dart
import 'package:drift/drift.dart';

@DataClassName('FavoriteRow')
class Favorites extends Table {
  IntColumn get tmdbId => integer()();
  TextColumn get mediaType => text()();
  DateTimeColumn get addedAt => dateTime().withDefault(currentDateAndTime)();

  @override
  Set<Column> get primaryKey => {tmdbId, mediaType};
}
```

- [ ] **Step 6: Write `watchlist.dart`**

```dart
import 'package:drift/drift.dart';

@DataClassName('WatchlistRow')
class Watchlist extends Table {
  IntColumn get tmdbId => integer()();
  TextColumn get mediaType => text()();
  DateTimeColumn get addedAt => dateTime().withDefault(currentDateAndTime)();

  @override
  Set<Column> get primaryKey => {tmdbId, mediaType};
}
```

- [ ] **Step 7: Write `user_settings.dart` (single-row table; key on a literal "user")**

```dart
import 'package:drift/drift.dart';

/// Single-row mirror of /api/settings. The single row uses key='user'.
@DataClassName('UserSettingsRow')
class UserSettings extends Table {
  TextColumn get key => text().withDefault(const Constant('user'))();
  TextColumn get audioPrefLang => text().withDefault(const Constant('ita'))();
  TextColumn get subsPrefLang => text().withDefault(const Constant('ita'))();
  IntColumn get qualityCapHeight => integer().nullable()();
  BoolColumn get autoplayNextEpisode => boolean().withDefault(const Constant(true))();
  BoolColumn get skipIntro => boolean().withDefault(const Constant(true))();
  TextColumn get theme => text().withDefault(const Constant('auto'))();
  TextColumn get locale => text().withDefault(const Constant('it-IT'))();
  DateTimeColumn get updatedAt => dateTime().withDefault(currentDateAndTime)();

  @override
  Set<Column> get primaryKey => {key};
}
```

- [ ] **Step 8: Write `outbox.dart`**

```dart
import 'package:drift/drift.dart';

/// Pending mutations not yet pushed to the backend. Drained by a background
/// isolate (sub-plan #6).
@DataClassName('OutboxRow')
class Outbox extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get kind => text()();        // e.g. "favorite.add"
  TextColumn get payloadJson => text()();
  DateTimeColumn get createdAt => dateTime().withDefault(currentDateAndTime)();
  IntColumn get attempts => integer().withDefault(const Constant(0))();
  DateTimeColumn get nextAttemptAt => dateTime().withDefault(currentDateAndTime)();
}
```

- [ ] **Step 9: Write `installed_plugins.dart`**

```dart
import 'package:drift/drift.dart';

@DataClassName('InstalledPluginRow')
class InstalledPlugins extends Table {
  TextColumn get shortName => text()();
  TextColumn get version => text()();
  TextColumn get sha256 => text()();
  TextColumn get filePath => text()();
  BoolColumn get enabled => boolean().withDefault(const Constant(true))();
  DateTimeColumn get installedAt => dateTime().withDefault(currentDateAndTime)();

  @override
  Set<Column> get primaryKey => {shortName};
}
```

- [ ] **Step 10: Write `plugin_kv.dart`**

```dart
import 'package:drift/drift.dart';

/// Backing store for the sandbox `host.storage` API (sub-plan #4).
/// Each plugin gets its own namespace; key is `(plugin_short_name, key)`.
@DataClassName('PluginKvRow')
class PluginKv extends Table {
  TextColumn get pluginShortName => text()();
  TextColumn get key => text()();
  TextColumn get value => text()();

  @override
  Set<Column> get primaryKey => {pluginShortName, key};
}
```

- [ ] **Step 11: Verify analyze**

```bash
flutter analyze lib/data/local/schema/
```

Expected: `No issues found!`.

- [ ] **Step 12: Commit**

```bash
git add lib/data/local/schema/
git commit -m "data: drift table definitions (10 tables, schema v1)"
```

---

### Task 9: `database.dart` with @DriftDatabase + code-gen

**Files:**
- Create: `lib/data/local/database.dart`

- [ ] **Step 1: Write `database.dart`**

```dart
// lib/data/local/database.dart
import 'package:drift/drift.dart';
import 'package:drift_flutter/drift_flutter.dart';

import 'schema/catalog_items.dart';
import 'schema/catalog_sources.dart';
import 'schema/favorites.dart';
import 'schema/installed_plugins.dart';
import 'schema/outbox.dart';
import 'schema/plugin_kv.dart';
import 'schema/tv_episodes.dart';
import 'schema/user_settings.dart';
import 'schema/watch_progress.dart';
import 'schema/watchlist.dart';

part 'database.g.dart';

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
])
class StreamloadDatabase extends _$StreamloadDatabase {
  StreamloadDatabase() : super(_open());
  StreamloadDatabase.test(QueryExecutor executor) : super(executor);

  @override
  int get schemaVersion => 1;

  static QueryExecutor _open() {
    // drift_flutter handles platform-appropriate paths (macOS application
    // support directory) and threading.
    return driftDatabase(name: 'streamload_v3');
  }
}
```

- [ ] **Step 2: Run drift code-gen**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
dart run build_runner build --delete-conflicting-outputs
```

Expected: generates `lib/data/local/database.g.dart`. No errors.

- [ ] **Step 3: Commit (the .g.dart goes with it)**

```bash
git add lib/data/local/database.dart lib/data/local/database.g.dart
git commit -m "data: drift database wired with all 10 tables (schema v1)"
```

---

### Task 10: Database boot test

**Files:**
- Create: `test/data/database_test.dart`

- [ ] **Step 1: Write the test FIRST**

```dart
// test/data/database_test.dart
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/data/local/database.dart';

void main() {
  late StreamloadDatabase db;

  setUp(() {
    db = StreamloadDatabase.test(NativeDatabase.memory());
  });

  tearDown(() async {
    await db.close();
  });

  test('schema v1 is created with all 10 tables', () async {
    final tables = await db.customSelect(
      "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
    ).get();
    final names = tables.map((r) => r.read<String>('name')).toList();
    expect(
      names,
      containsAll([
        'catalog_items',
        'catalog_sources',
        'favorites',
        'installed_plugins',
        'outbox',
        'plugin_kv',
        'tv_episodes',
        'user_settings',
        'watch_progress',
        'watchlist',
      ]),
    );
  });

  test('schemaVersion is 1', () {
    expect(db.schemaVersion, 1);
  });
}
```

- [ ] **Step 2: Run, expect pass**

```bash
flutter test test/data/database_test.dart
```

Expected: 2 tests pass.

- [ ] **Step 3: Commit**

```bash
git add test/data/database_test.dart
git commit -m "test(data): assert all 10 tables created at schema v1"
```

---

### Task 11: DAOs for catalog + user_settings (foundation only)

**Files:**
- Create: `lib/data/local/daos/catalog_dao.dart`
- Create: `lib/data/local/daos/user_settings_dao.dart`
- Create: `test/data/catalog_dao_test.dart`
- Create: `test/data/user_settings_dao_test.dart`
- Modify: `lib/data/local/database.dart` (add `daos: [...]`)

- [ ] **Step 1: Write `catalog_dao.dart`**

```dart
// lib/data/local/daos/catalog_dao.dart
import 'package:drift/drift.dart';

import '../database.dart';
import '../schema/catalog_items.dart';

part 'catalog_dao.g.dart';

@DriftAccessor(tables: [CatalogItems])
class CatalogDao extends DatabaseAccessor<StreamloadDatabase> with _$CatalogDaoMixin {
  CatalogDao(StreamloadDatabase db) : super(db);

  Future<CatalogItemRow?> get(int tmdbId, String mediaType) {
    return (select(catalogItems)
          ..where((t) => t.tmdbId.equals(tmdbId) & t.mediaType.equals(mediaType)))
        .getSingleOrNull();
  }

  Future<void> upsert(CatalogItemsCompanion entry) async {
    await into(catalogItems).insertOnConflictUpdate(entry);
  }

  Future<int> count() async {
    return await catalogItems.count().getSingle();
  }
}
```

- [ ] **Step 2: Write `user_settings_dao.dart`**

```dart
// lib/data/local/daos/user_settings_dao.dart
import 'package:drift/drift.dart';

import '../database.dart';
import '../schema/user_settings.dart';

part 'user_settings_dao.g.dart';

@DriftAccessor(tables: [UserSettings])
class UserSettingsDao extends DatabaseAccessor<StreamloadDatabase>
    with _$UserSettingsDaoMixin {
  UserSettingsDao(StreamloadDatabase db) : super(db);

  /// The single-row settings record. Returns the inserted defaults if absent.
  Future<UserSettingsRow> getOrSeed() async {
    final existing = await (select(userSettings)
          ..where((t) => t.key.equals('user')))
        .getSingleOrNull();
    if (existing != null) return existing;
    await into(userSettings).insert(const UserSettingsCompanion());
    return (select(userSettings)..where((t) => t.key.equals('user')))
        .getSingle();
  }

  /// Upsert from server payload. Caller has already converted the API DTO.
  Future<void> upsertFromServer({
    required String audioPrefLang,
    required String subsPrefLang,
    required int? qualityCapHeight,
    required bool autoplayNextEpisode,
    required bool skipIntro,
    required String theme,
    required String locale,
  }) async {
    await into(userSettings).insertOnConflictUpdate(UserSettingsCompanion(
      key: const Value('user'),
      audioPrefLang: Value(audioPrefLang),
      subsPrefLang: Value(subsPrefLang),
      qualityCapHeight: Value(qualityCapHeight),
      autoplayNextEpisode: Value(autoplayNextEpisode),
      skipIntro: Value(skipIntro),
      theme: Value(theme),
      locale: Value(locale),
      updatedAt: Value(DateTime.now()),
    ));
  }

  Stream<UserSettingsRow> watch() {
    return (select(userSettings)..where((t) => t.key.equals('user')))
        .watchSingleOrNull()
        .asyncMap((row) async => row ?? await getOrSeed());
  }
}
```

- [ ] **Step 3: Modify `database.dart` to register the DAOs**

Replace the `@DriftDatabase` annotation block:

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
])
```

Add the imports at the top:

```dart
import 'daos/catalog_dao.dart';
import 'daos/user_settings_dao.dart';
```

- [ ] **Step 4: Re-run code-gen**

```bash
dart run build_runner build --delete-conflicting-outputs
```

Expected: generates `catalog_dao.g.dart` and `user_settings_dao.g.dart`.

- [ ] **Step 5: Write the DAO tests**

```dart
// test/data/catalog_dao_test.dart
import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/data/local/database.dart';

void main() {
  late StreamloadDatabase db;

  setUp(() {
    db = StreamloadDatabase.test(NativeDatabase.memory());
  });

  tearDown(() => db.close());

  test('upsert + get round-trip', () async {
    await db.catalogDao.upsert(CatalogItemsCompanion.insert(
      tmdbId: 1396,
      mediaType: 'tv',
      title: 'Breaking Bad',
      year: const Value(2008),
      seasonsCount: const Value(5),
    ));
    final fetched = await db.catalogDao.get(1396, 'tv');
    expect(fetched, isNotNull);
    expect(fetched!.title, 'Breaking Bad');
    expect(fetched.year, 2008);
  });

  test('composite PK lets movie + tv with same id coexist', () async {
    await db.catalogDao.upsert(CatalogItemsCompanion.insert(
      tmdbId: 1396, mediaType: 'movie', title: 'Lo specchio',
    ));
    await db.catalogDao.upsert(CatalogItemsCompanion.insert(
      tmdbId: 1396, mediaType: 'tv', title: 'Breaking Bad',
    ));
    expect(await db.catalogDao.count(), 2);
    expect((await db.catalogDao.get(1396, 'movie'))!.title, 'Lo specchio');
    expect((await db.catalogDao.get(1396, 'tv'))!.title, 'Breaking Bad');
  });
}
```

```dart
// test/data/user_settings_dao_test.dart
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/data/local/database.dart';

void main() {
  late StreamloadDatabase db;

  setUp(() {
    db = StreamloadDatabase.test(NativeDatabase.memory());
  });

  tearDown(() => db.close());

  test('getOrSeed returns defaults on first call', () async {
    final s = await db.userSettingsDao.getOrSeed();
    expect(s.audioPrefLang, 'ita');
    expect(s.subsPrefLang, 'ita');
    expect(s.theme, 'auto');
    expect(s.autoplayNextEpisode, true);
  });

  test('upsertFromServer overwrites and persists', () async {
    await db.userSettingsDao.getOrSeed();
    await db.userSettingsDao.upsertFromServer(
      audioPrefLang: 'eng',
      subsPrefLang: 'ita',
      qualityCapHeight: 1080,
      autoplayNextEpisode: false,
      skipIntro: false,
      theme: 'dark',
      locale: 'en-US',
    );
    final s = await db.userSettingsDao.getOrSeed();
    expect(s.audioPrefLang, 'eng');
    expect(s.theme, 'dark');
    expect(s.qualityCapHeight, 1080);
  });
}
```

- [ ] **Step 6: Run tests, expect pass**

```bash
flutter test test/data/
```

Expected: all 6 data tests pass.

- [ ] **Step 7: Commit**

```bash
git add lib/data/local/daos/ lib/data/local/database.dart lib/data/local/*.g.dart test/data/catalog_dao_test.dart test/data/user_settings_dao_test.dart
git commit -m "data: CatalogDao + UserSettingsDao with round-trip tests"
```

---

### Task 12: `database_provider` (riverpod)

**Files:**
- Create: `lib/state/database_provider.dart`

- [ ] **Step 1: Write the provider**

```dart
// lib/state/database_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/local/database.dart';

/// Singleton drift database for the app's lifetime.
/// In tests, override with `databaseProvider.overrideWith((_) => StreamloadDatabase.test(...))`.
final databaseProvider = Provider<StreamloadDatabase>((ref) {
  final db = StreamloadDatabase();
  ref.onDispose(db.close);
  return db;
});
```

- [ ] **Step 2: Verify analyze**

```bash
flutter analyze lib/state/database_provider.dart
```

Expected: `No issues found!`.

- [ ] **Step 3: Commit**

```bash
git add lib/state/database_provider.dart
git commit -m "state: databaseProvider singleton"
```

---

## Phase D — Secure storage + env

### Task 13: Secure storage adapter

**Files:**
- Create: `lib/data/secure/secure_storage.dart`
- Create: `test/data/secure_storage_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/data/secure_storage_test.dart
//
// We don't unit-test the actual Keychain backend (requires platform); we
// confirm the wrapper exposes the right named accessors and round-trips
// through an injected map-backed implementation.
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/data/secure/secure_storage.dart';

class _MemoryBackend implements SecureKvBackend {
  final Map<String, String> _data = {};

  @override
  Future<String?> read(String key) async => _data[key];

  @override
  Future<void> write(String key, String value) async => _data[key] = value;

  @override
  Future<void> delete(String key) async => _data.remove(key);
}

void main() {
  late SecureStorage s;

  setUp(() {
    s = SecureStorage(backend: _MemoryBackend());
  });

  test('session cookie round-trips', () async {
    await s.setSessionCookie('abc=123');
    expect(await s.sessionCookie(), 'abc=123');
    await s.clearSessionCookie();
    expect(await s.sessionCookie(), isNull);
  });

  test('github PAT round-trips', () async {
    await s.setGithubPat('github_pat_xyz');
    expect(await s.githubPat(), 'github_pat_xyz');
    await s.clearGithubPat();
    expect(await s.githubPat(), isNull);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/data/secure_storage_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement the adapter**

```dart
// lib/data/secure/secure_storage.dart
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Pluggable backend so tests can use an in-memory map.
abstract class SecureKvBackend {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
}

class _FlutterSecureStorageBackend implements SecureKvBackend {
  static const _opts = IOSOptions(accessibility: KeychainAccessibility.first_unlock);
  static const _macOpts = MacOsOptions(accessibility: KeychainAccessibility.first_unlock);
  final _storage = const FlutterSecureStorage(iOptions: _opts, mOptions: _macOpts);

  @override
  Future<String?> read(String key) => _storage.read(key: key);

  @override
  Future<void> write(String key, String value) =>
      _storage.write(key: key, value: value);

  @override
  Future<void> delete(String key) => _storage.delete(key: key);
}

/// Typed Keychain accessors.
class SecureStorage {
  SecureStorage({SecureKvBackend? backend})
      : _backend = backend ?? _FlutterSecureStorageBackend();

  final SecureKvBackend _backend;

  static const _kSessionCookie = 'streamload.session_cookie';
  static const _kGithubPat = 'streamload.github_pat';

  Future<String?> sessionCookie() => _backend.read(_kSessionCookie);
  Future<void> setSessionCookie(String value) =>
      _backend.write(_kSessionCookie, value);
  Future<void> clearSessionCookie() => _backend.delete(_kSessionCookie);

  Future<String?> githubPat() => _backend.read(_kGithubPat);
  Future<void> setGithubPat(String value) => _backend.write(_kGithubPat, value);
  Future<void> clearGithubPat() => _backend.delete(_kGithubPat);
}
```

- [ ] **Step 4: Run, expect pass**

```bash
flutter test test/data/secure_storage_test.dart
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/data/secure/secure_storage.dart test/data/secure_storage_test.dart
git commit -m "data: SecureStorage with pluggable backend (Keychain in prod, memory in tests)"
```

---

### Task 14: `env.dart` + `logger.dart`

**Files:**
- Create: `lib/infra/env.dart`
- Create: `lib/infra/logger.dart`

- [ ] **Step 1: Write `env.dart`**

```dart
// lib/infra/env.dart
//
// Build-time environment. Inject the backend URL with:
//   flutter run --dart-define=STREAMLOAD_API_BASE_URL=https://your-vps.example.com
//
// Defaults to local dev server.

class Env {
  Env._();

  static const String apiBaseUrl = String.fromEnvironment(
    'STREAMLOAD_API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );
}
```

- [ ] **Step 2: Write `logger.dart`**

```dart
// lib/infra/logger.dart
//
// Tiny structured logger. Debug builds print to stdout; release strips info+below.

import 'package:flutter/foundation.dart';

enum LogLevel { debug, info, warn, error }

class Logger {
  Logger(this.tag);
  final String tag;

  void debug(String msg) => _log(LogLevel.debug, msg);
  void info(String msg) => _log(LogLevel.info, msg);
  void warn(String msg) => _log(LogLevel.warn, msg);
  void error(String msg, [Object? err, StackTrace? st]) {
    _log(LogLevel.error, '$msg${err != null ? ' — $err' : ''}');
    if (kDebugMode && st != null) debugPrint(st.toString());
  }

  void _log(LogLevel level, String msg) {
    if (!kDebugMode && level.index < LogLevel.warn.index) return;
    debugPrint('[${level.name.toUpperCase()}] $tag: $msg');
  }
}
```

- [ ] **Step 3: Verify analyze**

```bash
flutter analyze lib/infra/
```

Expected: `No issues found!`.

- [ ] **Step 4: Commit**

```bash
git add lib/infra/
git commit -m "infra: env (build-time API URL) + Logger (debug-stripping)"
```

---

## Phase E — ApiClient (HTTP layer)

### Task 15: ApiException

**Files:**
- Create: `lib/data/remote/api_exception.dart`
- Create: `test/data/remote/api_exception_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/data/remote/api_exception_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:streamload_client/data/remote/api_exception.dart';

void main() {
  test('formats message with status', () {
    final e = ApiException(401, 'unauthorized');
    expect(e.toString(), 'ApiException(401): unauthorized');
  });

  test('exposes detail when provided', () {
    final e = ApiException(422, 'invalid', detail: {'field': 'email'});
    expect(e.detail, {'field': 'email'});
  });

  test('isUnauthorized helper', () {
    expect(ApiException(401, 'x').isUnauthorized, isTrue);
    expect(ApiException(403, 'x').isUnauthorized, isFalse);
  });

  test('isNotFound helper', () {
    expect(ApiException(404, 'x').isNotFound, isTrue);
    expect(ApiException(500, 'x').isNotFound, isFalse);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/data/remote/api_exception_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement**

```dart
// lib/data/remote/api_exception.dart
class ApiException implements Exception {
  ApiException(this.status, this.message, {this.detail});

  final int status;
  final String message;
  final Object? detail;

  bool get isUnauthorized => status == 401;
  bool get isForbidden => status == 403;
  bool get isNotFound => status == 404;
  bool get isServerError => status >= 500;

  @override
  String toString() => 'ApiException($status): $message';
}
```

- [ ] **Step 4: Run, expect pass**

```bash
flutter test test/data/remote/api_exception_test.dart
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/data/remote/api_exception.dart test/data/remote/api_exception_test.dart
git commit -m "data(remote): ApiException with status helpers"
```

---

### Task 16: ApiClient (dio + cookie jar)

**Files:**
- Create: `lib/data/remote/api_client.dart`
- Create: `test/data/remote/api_client_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/data/remote/api_client_test.dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/api_client.dart';
import 'package:streamload_client/data/remote/api_exception.dart';

class _DioMock extends Mock implements Dio {}

class _FakeOptions extends Fake implements RequestOptions {}

void main() {
  setUpAll(() => registerFallbackValue(_FakeOptions()));

  test('GET decodes JSON body on 200', () async {
    final dio = _DioMock();
    when(() => dio.get<dynamic>(any(), queryParameters: any(named: 'queryParameters')))
        .thenAnswer((_) async => Response<dynamic>(
              data: {'ok': true},
              statusCode: 200,
              requestOptions: RequestOptions(path: '/x'),
            ));
    final client = ApiClient.test(dio);
    final out = await client.getJson('/x');
    expect(out, {'ok': true});
  });

  test('non-2xx maps to ApiException', () async {
    final dio = _DioMock();
    when(() => dio.get<dynamic>(any(), queryParameters: any(named: 'queryParameters')))
        .thenThrow(DioException(
          requestOptions: RequestOptions(path: '/x'),
          response: Response(
            statusCode: 401,
            data: {'detail': 'not authenticated'},
            requestOptions: RequestOptions(path: '/x'),
          ),
          type: DioExceptionType.badResponse,
        ));
    final client = ApiClient.test(dio);
    expect(
      () => client.getJson('/x'),
      throwsA(isA<ApiException>()
          .having((e) => e.status, 'status', 401)
          .having((e) => e.message, 'message', 'not authenticated')),
    );
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/data/remote/api_client_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement ApiClient**

```dart
// lib/data/remote/api_client.dart
import 'package:cookie_jar/cookie_jar.dart';
import 'package:dio/dio.dart';
import 'package:dio_cookie_manager/dio_cookie_manager.dart';
import 'package:path_provider/path_provider.dart';

import '../../infra/env.dart';
import 'api_exception.dart';

/// Dio wrapper. Owns the cookie jar so the backend session persists across
/// app restarts (jar lives in app support dir).
class ApiClient {
  ApiClient._(this._dio);

  /// Real client — call `await ApiClient.create()`.
  static Future<ApiClient> create() async {
    final supportDir = await getApplicationSupportDirectory();
    final jar = PersistCookieJar(
      ignoreExpires: false,
      storage: FileStorage('${supportDir.path}/cookies/'),
    );
    final dio = Dio(BaseOptions(
      baseUrl: Env.apiBaseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 30),
      headers: {'Accept': 'application/json'},
      validateStatus: (_) => true, // we map status → ApiException ourselves
    ));
    dio.interceptors.add(CookieManager(jar));
    return ApiClient._(dio);
  }

  /// Test ctor — inject your own Dio (typically a mocktail mock).
  ApiClient.test(this._dio);

  final Dio _dio;

  Dio get raw => _dio;

  Future<Map<String, dynamic>> getJson(
    String path, {
    Map<String, dynamic>? query,
  }) async {
    return _unwrap(
      () => _dio.get<dynamic>(path, queryParameters: query),
    );
  }

  Future<Map<String, dynamic>> postJson(
    String path, {
    Object? body,
    Map<String, dynamic>? query,
  }) async {
    return _unwrap(
      () => _dio.post<dynamic>(path, data: body, queryParameters: query),
    );
  }

  Future<Map<String, dynamic>> putJson(
    String path, {
    Object? body,
    Map<String, dynamic>? query,
  }) async {
    return _unwrap(
      () => _dio.put<dynamic>(path, data: body, queryParameters: query),
    );
  }

  Future<void> delete(String path, {Map<String, dynamic>? query}) async {
    await _unwrap(
      () => _dio.delete<dynamic>(path, queryParameters: query),
    );
  }

  Future<Map<String, dynamic>> _unwrap(
    Future<Response<dynamic>> Function() call,
  ) async {
    Response<dynamic> resp;
    try {
      resp = await call();
    } on DioException catch (e) {
      // Network error or thrown response.
      final r = e.response;
      if (r != null) {
        throw _toApi(r);
      }
      throw ApiException(0, e.message ?? 'network error');
    }
    if (resp.statusCode != null && resp.statusCode! >= 200 && resp.statusCode! < 300) {
      final body = resp.data;
      if (body is Map<String, dynamic>) return body;
      // 204 / empty body → return {}
      return <String, dynamic>{};
    }
    throw _toApi(resp);
  }

  ApiException _toApi(Response<dynamic> r) {
    final data = r.data;
    String msg = 'http ${r.statusCode}';
    Object? detail;
    if (data is Map && data['detail'] is String) {
      msg = data['detail'] as String;
    } else if (data is Map) {
      detail = data;
      if (data['message'] is String) msg = data['message'] as String;
    }
    return ApiException(r.statusCode ?? 0, msg, detail: detail);
  }
}
```

- [ ] **Step 4: Run, expect pass**

```bash
flutter test test/data/remote/api_client_test.dart
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/data/remote/api_client.dart test/data/remote/api_client_test.dart
git commit -m "data(remote): ApiClient with persistent cookie jar + ApiException mapping"
```

---

### Task 17: Domain models (User, Settings, CatalogItem) — freezed

**Files:**
- Create: `lib/domain/models/user.dart`
- Create: `lib/domain/models/settings.dart`
- Create: `lib/domain/models/catalog_item.dart`

- [ ] **Step 1: Write `user.dart`**

```dart
// lib/domain/models/user.dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'user.freezed.dart';
part 'user.g.dart';

@freezed
class User with _$User {
  const factory User({
    required String id,
    required String username,
    required String email,
    @JsonKey(name: 'email_verified') required bool emailVerified,
    required String role,
  }) = _User;

  factory User.fromJson(Map<String, dynamic> json) => _$UserFromJson(json);
}
```

- [ ] **Step 2: Write `settings.dart`**

```dart
// lib/domain/models/settings.dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'settings.freezed.dart';
part 'settings.g.dart';

@freezed
class UserSettingsModel with _$UserSettingsModel {
  const factory UserSettingsModel({
    @JsonKey(name: 'audio_pref_lang') @Default('ita') String audioPrefLang,
    @JsonKey(name: 'subs_pref_lang') @Default('ita') String subsPrefLang,
    @JsonKey(name: 'quality_cap_height') int? qualityCapHeight,
    @JsonKey(name: 'autoplay_next_episode') @Default(true) bool autoplayNextEpisode,
    @JsonKey(name: 'skip_intro') @Default(true) bool skipIntro,
    @Default('auto') String theme,
    @Default('it-IT') String locale,
  }) = _UserSettingsModel;

  factory UserSettingsModel.fromJson(Map<String, dynamic> json) =>
      _$UserSettingsModelFromJson(json);
}
```

- [ ] **Step 3: Write `catalog_item.dart`**

```dart
// lib/domain/models/catalog_item.dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'catalog_item.freezed.dart';
part 'catalog_item.g.dart';

@freezed
class SourceResponse with _$SourceResponse {
  const factory SourceResponse({
    required String label,
    required double score,
  }) = _SourceResponse;

  factory SourceResponse.fromJson(Map<String, dynamic> json) =>
      _$SourceResponseFromJson(json);
}

@freezed
class CatalogItemResponse with _$CatalogItemResponse {
  const factory CatalogItemResponse({
    @JsonKey(name: 'tmdb_id') required int tmdbId,
    @JsonKey(name: 'media_type') required String mediaType,
    required String title,
    @JsonKey(name: 'original_title') String? originalTitle,
    int? year,
    @JsonKey(name: 'poster_url') String? posterUrl,
    @JsonKey(name: 'backdrop_url') String? backdropUrl,
    String? overview,
    double? rating,
    @JsonKey(name: 'runtime_minutes') int? runtimeMinutes,
    @JsonKey(name: 'seasons_count') int? seasonsCount,
    @Default([]) List<String> genres,
    @Default([]) List<SourceResponse> sources,
  }) = _CatalogItemResponse;

  factory CatalogItemResponse.fromJson(Map<String, dynamic> json) =>
      _$CatalogItemResponseFromJson(json);
}
```

- [ ] **Step 4: Run code-gen**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
dart run build_runner build --delete-conflicting-outputs
```

Expected: generates `*.freezed.dart` and `*.g.dart` for the three models.

- [ ] **Step 5: Verify analyze**

```bash
flutter analyze lib/domain/
```

Expected: `No issues found!`.

- [ ] **Step 6: Commit**

```bash
git add lib/domain/models/
git commit -m "domain: User, UserSettingsModel, CatalogItemResponse (freezed)"
```

---

### Task 18: AuthApi + tests

**Files:**
- Create: `lib/data/remote/endpoints/auth_api.dart`
- Create: `test/data/remote/auth_api_test.dart`

- [ ] **Step 1: Write the failing tests FIRST**

```dart
// test/data/remote/auth_api_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/api_client.dart';
import 'package:streamload_client/data/remote/endpoints/auth_api.dart';

class _ClientMock extends Mock implements ApiClient {}

void main() {
  late _ClientMock client;
  late AuthApi api;

  setUp(() {
    client = _ClientMock();
    api = AuthApi(client);
  });

  test('login posts to /auth/login and parses User', () async {
    when(() => client.postJson(
          '/api/auth/login',
          body: {'username': 'alice', 'password': 'pw'},
        )).thenAnswer((_) async => {
              'id': 'u1',
              'username': 'alice',
              'email': 'a@x.com',
              'email_verified': true,
              'role': 'user',
            });
    final u = await api.login(username: 'alice', password: 'pw');
    expect(u.username, 'alice');
    expect(u.role, 'user');
  });

  test('register posts to /auth/register', () async {
    when(() => client.postJson(
          '/api/auth/register',
          body: {'username': 'bob', 'email': 'b@x.com', 'password': 'pw'},
        )).thenAnswer((_) async => {
              'id': 'u2',
              'username': 'bob',
              'email': 'b@x.com',
              'email_verified': true,
              'role': 'user',
            });
    final u = await api.register(username: 'bob', email: 'b@x.com', password: 'pw');
    expect(u.username, 'bob');
  });

  test('me hits /me', () async {
    when(() => client.getJson('/api/me')).thenAnswer((_) async => {
          'id': 'u1',
          'username': 'alice',
          'email': 'a@x.com',
          'email_verified': true,
          'role': 'user',
        });
    final u = await api.me();
    expect(u.id, 'u1');
  });

  test('logout calls /auth/logout', () async {
    when(() => client.postJson('/api/auth/logout')).thenAnswer((_) async => {});
    await api.logout();
    verify(() => client.postJson('/api/auth/logout')).called(1);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/data/remote/auth_api_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement AuthApi**

```dart
// lib/data/remote/endpoints/auth_api.dart
import '../../../domain/models/user.dart';
import '../api_client.dart';

class AuthApi {
  AuthApi(this._client);
  final ApiClient _client;

  Future<User> login({required String username, required String password}) async {
    final json = await _client.postJson(
      '/api/auth/login',
      body: {'username': username, 'password': password},
    );
    return User.fromJson(json);
  }

  Future<User> register({
    required String username,
    required String email,
    required String password,
  }) async {
    final json = await _client.postJson(
      '/api/auth/register',
      body: {'username': username, 'email': email, 'password': password},
    );
    return User.fromJson(json);
  }

  Future<User> me() async {
    final json = await _client.getJson('/api/me');
    return User.fromJson(json);
  }

  Future<void> logout() async {
    await _client.postJson('/api/auth/logout');
  }
}
```

- [ ] **Step 4: Run, expect pass**

```bash
flutter test test/data/remote/auth_api_test.dart
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/data/remote/endpoints/auth_api.dart test/data/remote/auth_api_test.dart
git commit -m "data(api): AuthApi (login/register/logout/me)"
```

---

### Task 19: Catalog / Collections / Episodes / Library APIs

**Files:**
- Create: `lib/data/remote/endpoints/catalog_api.dart`
- Create: `lib/data/remote/endpoints/collections_api.dart`
- Create: `lib/data/remote/endpoints/episodes_api.dart`
- Create: `lib/data/remote/endpoints/library_api.dart`
- Create: `test/data/remote/catalog_api_test.dart`

- [ ] **Step 1: Write `catalog_api.dart`**

```dart
// lib/data/remote/endpoints/catalog_api.dart
import '../../../domain/models/catalog_item.dart';
import '../api_client.dart';

class CatalogApi {
  CatalogApi(this._client);
  final ApiClient _client;

  /// GET /api/catalog/{tmdb_id}?media_type=movie|tv
  Future<CatalogItemResponse> get(int tmdbId, {String? mediaType}) async {
    final json = await _client.getJson(
      '/api/catalog/$tmdbId',
      query: {if (mediaType != null) 'media_type': mediaType},
    );
    return CatalogItemResponse.fromJson(json);
  }
}
```

- [ ] **Step 2: Write `collections_api.dart`**

```dart
// lib/data/remote/endpoints/collections_api.dart
import '../api_client.dart';

class CollectionsApi {
  CollectionsApi(this._client);
  final ApiClient _client;

  /// GET /api/collections — list all collection summaries.
  Future<List<Map<String, dynamic>>> list() async {
    final raw = await _client.raw.get<dynamic>('/api/collections');
    final data = raw.data;
    if (data is! List) return const [];
    return data.cast<Map<String, dynamic>>();
  }

  /// GET /api/collections/{id} — collection detail with items.
  Future<Map<String, dynamic>> get(String id) async {
    return _client.getJson('/api/collections/$id');
  }
}
```

- [ ] **Step 3: Write `episodes_api.dart`**

```dart
// lib/data/remote/endpoints/episodes_api.dart
import '../api_client.dart';

class EpisodesApi {
  EpisodesApi(this._client);
  final ApiClient _client;

  /// GET /api/title/{tmdb_id}/episodes — seasons + episodes for a TV title.
  Future<Map<String, dynamic>> list(int tmdbId) async {
    return _client.getJson('/api/title/$tmdbId/episodes');
  }
}
```

- [ ] **Step 4: Write `library_api.dart`**

```dart
// lib/data/remote/endpoints/library_api.dart
import '../api_client.dart';

class LibraryApi {
  LibraryApi(this._client);
  final ApiClient _client;

  /// GET /api/library?media_type=&page=
  Future<Map<String, dynamic>> page({
    String? mediaType,
    int page = 1,
    int perPage = 24,
  }) async {
    return _client.getJson('/api/library', query: {
      if (mediaType != null) 'media_type': mediaType,
      'page': page,
      'per_page': perPage,
    });
  }
}
```

- [ ] **Step 5: Write the catalog test (sample integration test)**

```dart
// test/data/remote/catalog_api_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/api_client.dart';
import 'package:streamload_client/data/remote/endpoints/catalog_api.dart';

class _ClientMock extends Mock implements ApiClient {}

void main() {
  test('catalog.get with media_type appends query', () async {
    final client = _ClientMock();
    when(() => client.getJson('/api/catalog/1396',
        query: {'media_type': 'tv'})).thenAnswer((_) async => {
          'tmdb_id': 1396,
          'media_type': 'tv',
          'title': 'Breaking Bad',
          'original_title': null,
          'year': 2008,
          'poster_url': null,
          'backdrop_url': null,
          'overview': null,
          'rating': null,
          'runtime_minutes': null,
          'seasons_count': 5,
          'genres': <String>[],
          'sources': <Map<String, dynamic>>[],
        });
    final api = CatalogApi(client);
    final item = await api.get(1396, mediaType: 'tv');
    expect(item.title, 'Breaking Bad');
    expect(item.seasonsCount, 5);
    expect(item.sources, isEmpty);
  });
}
```

- [ ] **Step 6: Run analyze + tests**

```bash
flutter analyze lib/data/remote/endpoints/
flutter test test/data/remote/catalog_api_test.dart
```

Expected: no issues, 1 test passes.

- [ ] **Step 7: Commit**

```bash
git add lib/data/remote/endpoints/{catalog,collections,episodes,library}_api.dart test/data/remote/catalog_api_test.dart
git commit -m "data(api): CatalogApi + CollectionsApi + EpisodesApi + LibraryApi"
```

---

### Task 20: Search / Intro / NextUp APIs

**Files:**
- Create: `lib/data/remote/endpoints/search_api.dart`
- Create: `lib/data/remote/endpoints/intro_api.dart`
- Create: `lib/data/remote/endpoints/next_up_api.dart`
- Create: `test/data/remote/search_api_test.dart`

- [ ] **Step 1: Write `search_api.dart`**

```dart
// lib/data/remote/endpoints/search_api.dart
import '../api_client.dart';

class SearchApi {
  SearchApi(this._client);
  final ApiClient _client;

  /// GET /api/search?q=foo
  Future<Map<String, dynamic>> run(String query) async {
    return _client.getJson('/api/search', query: {'q': query});
  }
}
```

- [ ] **Step 2: Write `intro_api.dart`**

```dart
// lib/data/remote/endpoints/intro_api.dart
import '../api_client.dart';
import '../api_exception.dart';

class IntroApi {
  IntroApi(this._client);
  final ApiClient _client;

  /// GET /api/intro/{tmdb_id}/s{season} → null on 204.
  Future<Map<String, dynamic>?> get(int tmdbId, int season) async {
    try {
      return await _client.getJson('/api/intro/$tmdbId/s$season');
    } on ApiException catch (e) {
      if (e.status == 204) return null;
      rethrow;
    }
  }
}
```

- [ ] **Step 3: Write `next_up_api.dart`**

```dart
// lib/data/remote/endpoints/next_up_api.dart
import '../api_client.dart';
import '../api_exception.dart';

class NextUpApi {
  NextUpApi(this._client);
  final ApiClient _client;

  /// GET /api/next-up/{tmdb_id}?season=&episode= → null on 204 (end of series).
  Future<Map<String, dynamic>?> get({
    required int tmdbId,
    required int season,
    required int episode,
  }) async {
    try {
      return await _client.getJson(
        '/api/next-up/$tmdbId',
        query: {'season': season, 'episode': episode},
      );
    } on ApiException catch (e) {
      if (e.status == 204) return null;
      rethrow;
    }
  }
}
```

- [ ] **Step 4: Write the search test**

```dart
// test/data/remote/search_api_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/api_client.dart';
import 'package:streamload_client/data/remote/endpoints/search_api.dart';

class _ClientMock extends Mock implements ApiClient {}

void main() {
  test('search hits /api/search with the q param', () async {
    final client = _ClientMock();
    when(() => client.getJson('/api/search', query: {'q': 'inception'}))
        .thenAnswer((_) async => {
              'query': 'inception',
              'results': <Map<String, dynamic>>[],
            });
    final api = SearchApi(client);
    final out = await api.run('inception');
    expect(out['query'], 'inception');
  });
}
```

- [ ] **Step 5: Run tests**

```bash
flutter test test/data/remote/search_api_test.dart
```

Expected: 1 test passes.

- [ ] **Step 6: Commit**

```bash
git add lib/data/remote/endpoints/{search,intro,next_up}_api.dart test/data/remote/search_api_test.dart
git commit -m "data(api): SearchApi + IntroApi + NextUpApi (204-aware for null cases)"
```

---

### Task 21: Progress / Favorites / Watchlist / Settings / Events APIs

**Files:**
- Create: `lib/data/remote/endpoints/progress_api.dart`
- Create: `lib/data/remote/endpoints/favorites_api.dart`
- Create: `lib/data/remote/endpoints/watchlist_api.dart`
- Create: `lib/data/remote/endpoints/settings_api.dart`
- Create: `lib/data/remote/endpoints/events_api.dart`
- Create: `test/data/remote/progress_api_test.dart`
- Create: `test/data/remote/favorites_api_test.dart`
- Create: `test/data/remote/settings_api_test.dart`

- [ ] **Step 1: Write `progress_api.dart`**

```dart
// lib/data/remote/endpoints/progress_api.dart
import '../api_client.dart';

class ProgressApi {
  ProgressApi(this._client);
  final ApiClient _client;

  /// POST /api/progress
  Future<Map<String, dynamic>> post({
    required int tmdbId,
    required String mediaType,
    int? seasonNumber,
    int? episodeNumber,
    required int positionSeconds,
    required int durationSeconds,
  }) async {
    return _client.postJson('/api/progress', body: {
      'tmdb_id': tmdbId,
      'media_type': mediaType,
      if (seasonNumber != null) 'season_number': seasonNumber,
      if (episodeNumber != null) 'episode_number': episodeNumber,
      'position_seconds': positionSeconds,
      'duration_seconds': durationSeconds,
    });
  }

  /// GET /api/progress/continue-watching
  Future<Map<String, dynamic>> continueWatching() async {
    return _client.getJson('/api/progress/continue-watching');
  }
}
```

- [ ] **Step 2: Write `favorites_api.dart`**

```dart
// lib/data/remote/endpoints/favorites_api.dart
import '../api_client.dart';

class FavoritesApi {
  FavoritesApi(this._client);
  final ApiClient _client;

  /// GET /api/favorites
  Future<List<Map<String, dynamic>>> list() async {
    final raw = await _client.raw.get<dynamic>('/api/favorites');
    final data = raw.data;
    if (data is! List) return const [];
    return data.cast<Map<String, dynamic>>();
  }

  /// POST /api/favorites/{tmdb_id}?media_type=
  Future<void> add(int tmdbId, String mediaType) async {
    await _client.postJson(
      '/api/favorites/$tmdbId',
      query: {'media_type': mediaType},
    );
  }

  /// DELETE /api/favorites/{tmdb_id}?media_type=
  Future<void> remove(int tmdbId, String mediaType) async {
    await _client.delete(
      '/api/favorites/$tmdbId',
      query: {'media_type': mediaType},
    );
  }
}
```

- [ ] **Step 3: Write `watchlist_api.dart`**

```dart
// lib/data/remote/endpoints/watchlist_api.dart
import '../api_client.dart';

class WatchlistApi {
  WatchlistApi(this._client);
  final ApiClient _client;

  Future<List<Map<String, dynamic>>> list() async {
    final raw = await _client.raw.get<dynamic>('/api/watchlist');
    final data = raw.data;
    if (data is! List) return const [];
    return data.cast<Map<String, dynamic>>();
  }

  Future<void> add(int tmdbId, String mediaType) async {
    await _client.postJson(
      '/api/watchlist/$tmdbId',
      query: {'media_type': mediaType},
    );
  }

  Future<void> remove(int tmdbId, String mediaType) async {
    await _client.delete(
      '/api/watchlist/$tmdbId',
      query: {'media_type': mediaType},
    );
  }
}
```

- [ ] **Step 4: Write `settings_api.dart`**

```dart
// lib/data/remote/endpoints/settings_api.dart
import '../../../domain/models/settings.dart';
import '../api_client.dart';

class SettingsApi {
  SettingsApi(this._client);
  final ApiClient _client;

  /// GET /api/settings
  Future<UserSettingsModel> get() async {
    final json = await _client.getJson('/api/settings');
    return UserSettingsModel.fromJson(json);
  }

  /// PUT /api/settings
  Future<UserSettingsModel> update(UserSettingsModel settings) async {
    final json = await _client.putJson('/api/settings', body: settings.toJson());
    return UserSettingsModel.fromJson(json);
  }
}
```

- [ ] **Step 5: Write `events_api.dart`**

```dart
// lib/data/remote/endpoints/events_api.dart
import '../api_client.dart';

class EventsApi {
  EventsApi(this._client);
  final ApiClient _client;

  /// POST /api/events with a batch (max 100 per call).
  Future<int> postBatch({
    String? appVersion,
    required List<({String type, Map<String, dynamic> payload})> events,
  }) async {
    final body = await _client.postJson('/api/events', body: {
      if (appVersion != null) 'app_version': appVersion,
      'events': events
          .map((e) => {'event_type': e.type, 'payload': e.payload})
          .toList(),
    });
    return (body['accepted'] as num?)?.toInt() ?? 0;
  }
}
```

- [ ] **Step 6: Write the three tests**

```dart
// test/data/remote/progress_api_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/api_client.dart';
import 'package:streamload_client/data/remote/endpoints/progress_api.dart';

class _ClientMock extends Mock implements ApiClient {}

void main() {
  test('post sends the full TV payload', () async {
    final client = _ClientMock();
    when(() => client.postJson('/api/progress', body: {
          'tmdb_id': 1396,
          'media_type': 'tv',
          'season_number': 3,
          'episode_number': 7,
          'position_seconds': 754,
          'duration_seconds': 2880,
        })).thenAnswer((_) async => {'status': 'ok', 'completed': 'false'});
    final api = ProgressApi(client);
    final out = await api.post(
      tmdbId: 1396,
      mediaType: 'tv',
      seasonNumber: 3,
      episodeNumber: 7,
      positionSeconds: 754,
      durationSeconds: 2880,
    );
    expect(out['status'], 'ok');
  });
}
```

```dart
// test/data/remote/favorites_api_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/api_client.dart';
import 'package:streamload_client/data/remote/endpoints/favorites_api.dart';

class _ClientMock extends Mock implements ApiClient {}

void main() {
  test('add posts with media_type query', () async {
    final client = _ClientMock();
    when(() => client.postJson(
          '/api/favorites/42',
          query: {'media_type': 'movie'},
        )).thenAnswer((_) async => {'status': 'added'});
    await FavoritesApi(client).add(42, 'movie');
    verify(() => client.postJson(
          '/api/favorites/42',
          query: {'media_type': 'movie'},
        )).called(1);
  });

  test('remove deletes with media_type query', () async {
    final client = _ClientMock();
    when(() => client.delete(
          '/api/favorites/42',
          query: {'media_type': 'movie'},
        )).thenAnswer((_) async {});
    await FavoritesApi(client).remove(42, 'movie');
    verify(() => client.delete(
          '/api/favorites/42',
          query: {'media_type': 'movie'},
        )).called(1);
  });
}
```

```dart
// test/data/remote/settings_api_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/api_client.dart';
import 'package:streamload_client/data/remote/endpoints/settings_api.dart';
import 'package:streamload_client/domain/models/settings.dart';

class _ClientMock extends Mock implements ApiClient {}

void main() {
  test('get returns parsed UserSettingsModel', () async {
    final client = _ClientMock();
    when(() => client.getJson('/api/settings')).thenAnswer((_) async => {
          'audio_pref_lang': 'eng',
          'subs_pref_lang': 'ita',
          'quality_cap_height': 1080,
          'autoplay_next_episode': false,
          'skip_intro': false,
          'theme': 'dark',
          'locale': 'en-US',
        });
    final s = await SettingsApi(client).get();
    expect(s.audioPrefLang, 'eng');
    expect(s.theme, 'dark');
    expect(s.qualityCapHeight, 1080);
  });

  test('update PUTs the serialized settings', () async {
    final client = _ClientMock();
    final input = const UserSettingsModel(theme: 'dark');
    when(() => client.putJson('/api/settings', body: input.toJson()))
        .thenAnswer((_) async => input.toJson());
    final out = await SettingsApi(client).update(input);
    expect(out.theme, 'dark');
  });
}
```

- [ ] **Step 7: Run all the new tests**

```bash
flutter test test/data/remote/
```

Expected: all green (8 tests across this batch + previous endpoint tests).

- [ ] **Step 8: Commit**

```bash
git add lib/data/remote/endpoints/{progress,favorites,watchlist,settings,events}_api.dart test/data/remote/{progress,favorites,settings}_api_test.dart
git commit -m "data(api): Progress/Favorites/Watchlist/Settings/Events APIs + tests"
```

---

### Task 22: AdminApi (typed stubs, no UI yet)

**Files:**
- Create: `lib/data/remote/endpoints/admin_api.dart`

- [ ] **Step 1: Write the typed stubs**

```dart
// lib/data/remote/endpoints/admin_api.dart
//
// Admin endpoints. Only an admin user can hit these (server enforces).
// No UI consumes them in sub-plan #3 — they exist so sub-plan #6 (admin
// portal) can plug straight in.

import '../api_client.dart';

class AdminApi {
  AdminApi(this._client);
  final ApiClient _client;

  /// GET /api/admin/users
  Future<List<Map<String, dynamic>>> users() async {
    final raw = await _client.raw.get<dynamic>('/api/admin/users');
    final data = raw.data;
    if (data is! List) return const [];
    return data.cast<Map<String, dynamic>>();
  }

  /// PUT /api/admin/users/{id}/role
  Future<void> setRole(String userId, String role) async {
    await _client.putJson('/api/admin/users/$userId/role', body: {'role': role});
  }

  /// POST /api/admin/users/{id}/disable
  Future<void> disable(String userId) async {
    await _client.postJson('/api/admin/users/$userId/disable');
  }

  /// POST /api/admin/users/{id}/enable
  Future<void> enable(String userId) async {
    await _client.postJson('/api/admin/users/$userId/enable');
  }

  /// POST /api/admin/users/{id}/reset-password
  Future<void> resetPassword(String userId, String password) async {
    await _client.postJson(
      '/api/admin/users/$userId/reset-password',
      body: {'password': password},
    );
  }

  /// DELETE /api/admin/users/{id}
  Future<void> deleteUser(String userId) async {
    await _client.delete('/api/admin/users/$userId');
  }

  /// GET /api/admin/stats
  Future<Map<String, dynamic>> stats() async {
    return _client.getJson('/api/admin/stats');
  }

  /// GET /api/admin/top-watched
  Future<List<Map<String, dynamic>>> topWatched() async {
    final raw = await _client.raw.get<dynamic>('/api/admin/top-watched');
    final data = raw.data;
    if (data is! List) return const [];
    return data.cast<Map<String, dynamic>>();
  }
}
```

- [ ] **Step 2: Verify analyze**

```bash
flutter analyze lib/data/remote/endpoints/admin_api.dart
```

Expected: `No issues found!`.

- [ ] **Step 3: Commit**

```bash
git add lib/data/remote/endpoints/admin_api.dart
git commit -m "data(api): AdminApi typed stubs (no UI yet — sub-plan #6 consumer)"
```

---

## Phase F — State / providers

### Task 23: ApiClient provider

**Files:**
- Create: `lib/state/api_client_provider.dart`

- [ ] **Step 1: Write the provider**

```dart
// lib/state/api_client_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/remote/api_client.dart';
import '../data/remote/endpoints/admin_api.dart';
import '../data/remote/endpoints/auth_api.dart';
import '../data/remote/endpoints/catalog_api.dart';
import '../data/remote/endpoints/collections_api.dart';
import '../data/remote/endpoints/episodes_api.dart';
import '../data/remote/endpoints/events_api.dart';
import '../data/remote/endpoints/favorites_api.dart';
import '../data/remote/endpoints/intro_api.dart';
import '../data/remote/endpoints/library_api.dart';
import '../data/remote/endpoints/next_up_api.dart';
import '../data/remote/endpoints/progress_api.dart';
import '../data/remote/endpoints/search_api.dart';
import '../data/remote/endpoints/settings_api.dart';
import '../data/remote/endpoints/watchlist_api.dart';

/// Async — created once at app boot. Override in tests with a fake ApiClient.
final apiClientProvider = FutureProvider<ApiClient>((ref) async {
  return ApiClient.create();
});

/// Convenience family of typed API providers, each pulling from apiClientProvider.
final authApiProvider = FutureProvider<AuthApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return AuthApi(c);
});

final catalogApiProvider = FutureProvider<CatalogApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return CatalogApi(c);
});

final collectionsApiProvider = FutureProvider<CollectionsApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return CollectionsApi(c);
});

final episodesApiProvider = FutureProvider<EpisodesApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return EpisodesApi(c);
});

final searchApiProvider = FutureProvider<SearchApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return SearchApi(c);
});

final introApiProvider = FutureProvider<IntroApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return IntroApi(c);
});

final nextUpApiProvider = FutureProvider<NextUpApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return NextUpApi(c);
});

final progressApiProvider = FutureProvider<ProgressApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return ProgressApi(c);
});

final favoritesApiProvider = FutureProvider<FavoritesApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return FavoritesApi(c);
});

final watchlistApiProvider = FutureProvider<WatchlistApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return WatchlistApi(c);
});

final libraryApiProvider = FutureProvider<LibraryApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return LibraryApi(c);
});

final settingsApiProvider = FutureProvider<SettingsApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return SettingsApi(c);
});

final eventsApiProvider = FutureProvider<EventsApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return EventsApi(c);
});

final adminApiProvider = FutureProvider<AdminApi>((ref) async {
  final c = await ref.watch(apiClientProvider.future);
  return AdminApi(c);
});
```

- [ ] **Step 2: Verify analyze**

```bash
flutter analyze lib/state/api_client_provider.dart
```

Expected: `No issues found!`.

- [ ] **Step 3: Commit**

```bash
git add lib/state/api_client_provider.dart
git commit -m "state: api_client_provider + typed FutureProviders for every endpoint"
```

---

### Task 24: Auth provider

**Files:**
- Create: `lib/state/auth_provider.dart`
- Create: `test/state/auth_provider_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/state/auth_provider_test.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/api_exception.dart';
import 'package:streamload_client/data/remote/endpoints/auth_api.dart';
import 'package:streamload_client/domain/models/user.dart';
import 'package:streamload_client/state/api_client_provider.dart';
import 'package:streamload_client/state/auth_provider.dart';

class _AuthApiMock extends Mock implements AuthApi {}

void main() {
  test('on app start with stored cookie + valid /me → authenticated', () async {
    final auth = _AuthApiMock();
    when(() => auth.me()).thenAnswer((_) async => const User(
          id: 'u1', username: 'alice', email: 'a@x.com',
          emailVerified: true, role: 'user',
        ));
    final container = ProviderContainer(overrides: [
      authApiProvider.overrideWith((_) async => auth),
    ]);
    addTearDown(container.dispose);

    // Trigger
    await container.read(authProvider.notifier).bootstrap();
    final state = container.read(authProvider);
    expect(state, isA<AuthAuthenticated>());
    expect((state as AuthAuthenticated).user.username, 'alice');
  });

  test('on app start with no cookie / 401 → unauthenticated', () async {
    final auth = _AuthApiMock();
    when(() => auth.me()).thenThrow(ApiException(401, 'not authenticated'));
    final container = ProviderContainer(overrides: [
      authApiProvider.overrideWith((_) async => auth),
    ]);
    addTearDown(container.dispose);

    await container.read(authProvider.notifier).bootstrap();
    expect(container.read(authProvider), isA<AuthUnauthenticated>());
  });

  test('login on success transitions state to authenticated', () async {
    final auth = _AuthApiMock();
    when(() => auth.login(username: 'alice', password: 'pw'))
        .thenAnswer((_) async => const User(
              id: 'u1', username: 'alice', email: 'a@x.com',
              emailVerified: true, role: 'user',
            ));
    final container = ProviderContainer(overrides: [
      authApiProvider.overrideWith((_) async => auth),
    ]);
    addTearDown(container.dispose);

    await container.read(authProvider.notifier).login(
          username: 'alice', password: 'pw',
        );
    expect(container.read(authProvider), isA<AuthAuthenticated>());
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/state/auth_provider_test.dart
```

Expected: import error (provider doesn't exist).

- [ ] **Step 3: Implement the provider**

```dart
// lib/state/auth_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/remote/api_exception.dart';
import '../domain/models/user.dart';
import 'api_client_provider.dart';

sealed class AuthState {
  const AuthState();
}

class AuthLoading extends AuthState {
  const AuthLoading();
}

class AuthUnauthenticated extends AuthState {
  const AuthUnauthenticated();
}

class AuthAuthenticated extends AuthState {
  const AuthAuthenticated(this.user);
  final User user;
}

class AuthError extends AuthState {
  const AuthError(this.message);
  final String message;
}

class AuthNotifier extends StateNotifier<AuthState> {
  AuthNotifier(this._ref) : super(const AuthLoading());

  final Ref _ref;

  /// Called once at app start. Hits /me; success → authenticated, 401 →
  /// unauthenticated, anything else → error.
  Future<void> bootstrap() async {
    state = const AuthLoading();
    try {
      final api = await _ref.read(authApiProvider.future);
      final user = await api.me();
      state = AuthAuthenticated(user);
    } on ApiException catch (e) {
      if (e.isUnauthorized) {
        state = const AuthUnauthenticated();
      } else {
        state = AuthError(e.toString());
      }
    } catch (e) {
      state = AuthError(e.toString());
    }
  }

  Future<void> login({required String username, required String password}) async {
    state = const AuthLoading();
    try {
      final api = await _ref.read(authApiProvider.future);
      final user = await api.login(username: username, password: password);
      state = AuthAuthenticated(user);
    } on ApiException catch (e) {
      state = AuthError(e.message);
      rethrow;
    }
  }

  Future<void> register({
    required String username,
    required String email,
    required String password,
  }) async {
    state = const AuthLoading();
    try {
      final api = await _ref.read(authApiProvider.future);
      final user = await api.register(
        username: username, email: email, password: password,
      );
      state = AuthAuthenticated(user);
    } on ApiException catch (e) {
      state = AuthError(e.message);
      rethrow;
    }
  }

  Future<void> logout() async {
    try {
      final api = await _ref.read(authApiProvider.future);
      await api.logout();
    } catch (_) {/* swallow — we still log out locally */}
    state = const AuthUnauthenticated();
  }
}

final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  return AuthNotifier(ref);
});
```

- [ ] **Step 4: Run, expect pass**

```bash
flutter test test/state/auth_provider_test.dart
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/state/auth_provider.dart test/state/auth_provider_test.dart
git commit -m "state: AuthNotifier with bootstrap/login/register/logout transitions"
```

---

### Task 25: Settings provider

**Files:**
- Create: `lib/state/settings_provider.dart`
- Create: `test/state/settings_provider_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/state/settings_provider_test.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/settings_api.dart';
import 'package:streamload_client/domain/models/settings.dart';
import 'package:streamload_client/state/api_client_provider.dart';
import 'package:streamload_client/state/settings_provider.dart';

class _SettingsApiMock extends Mock implements SettingsApi {}

void main() {
  setUpAll(() => registerFallbackValue(const UserSettingsModel()));

  test('reads server defaults on first build', () async {
    final api = _SettingsApiMock();
    when(api.get).thenAnswer((_) async => const UserSettingsModel());
    final container = ProviderContainer(overrides: [
      settingsApiProvider.overrideWith((_) async => api),
    ]);
    addTearDown(container.dispose);

    final s = await container.read(settingsFutureProvider.future);
    expect(s.audioPrefLang, 'ita');
    expect(s.theme, 'auto');
  });

  test('save round-trips through update', () async {
    final api = _SettingsApiMock();
    when(api.get).thenAnswer((_) async => const UserSettingsModel());
    when(() => api.update(any())).thenAnswer((inv) async {
      return inv.positionalArguments.first as UserSettingsModel;
    });
    final container = ProviderContainer(overrides: [
      settingsApiProvider.overrideWith((_) async => api),
    ]);
    addTearDown(container.dispose);

    final updated = const UserSettingsModel(theme: 'dark', audioPrefLang: 'eng');
    final out = await container.read(settingsControllerProvider.notifier).save(updated);
    expect(out.theme, 'dark');
    expect(out.audioPrefLang, 'eng');
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/state/settings_provider_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement the provider**

```dart
// lib/state/settings_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/models/settings.dart';
import 'api_client_provider.dart';

/// Read-only view: hits /api/settings each time the provider is built.
final settingsFutureProvider = FutureProvider<UserSettingsModel>((ref) async {
  final api = await ref.watch(settingsApiProvider.future);
  return api.get();
});

/// Controller for mutations. Saves to the server and invalidates the
/// settingsFutureProvider so consumers refresh.
class SettingsController extends StateNotifier<AsyncValue<UserSettingsModel>> {
  SettingsController(this._ref) : super(const AsyncLoading()) {
    _refresh();
  }

  final Ref _ref;

  Future<void> _refresh() async {
    state = const AsyncLoading();
    try {
      final api = await _ref.read(settingsApiProvider.future);
      final s = await api.get();
      state = AsyncData(s);
    } catch (e, st) {
      state = AsyncError(e, st);
    }
  }

  /// Persist server-side and update local state.
  Future<UserSettingsModel> save(UserSettingsModel next) async {
    final api = await _ref.read(settingsApiProvider.future);
    final saved = await api.update(next);
    state = AsyncData(saved);
    _ref.invalidate(settingsFutureProvider);
    return saved;
  }
}

final settingsControllerProvider =
    StateNotifierProvider<SettingsController, AsyncValue<UserSettingsModel>>(
  (ref) => SettingsController(ref),
);
```

- [ ] **Step 4: Run, expect pass**

```bash
flutter test test/state/settings_provider_test.dart
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/state/settings_provider.dart test/state/settings_provider_test.dart
git commit -m "state: settings providers (read-only Future + mutating controller)"
```

---

## Phase G — Routing + auth pages

### Task 26: `router.dart` with auth redirect

**Files:**
- Create: `lib/router.dart`

- [ ] **Step 1: Write the router**

```dart
// lib/router.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'presentation/pages/home_page.dart';
import 'presentation/pages/login_page.dart';
import 'presentation/pages/profile_page.dart';
import 'presentation/pages/register_page.dart';
import 'presentation/pages/settings_page.dart';
import 'state/auth_provider.dart';

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/login',
    debugLogDiagnostics: false,
    redirect: (context, state) {
      final auth = ref.read(authProvider);
      final isAuthRoute = state.matchedLocation == '/login' ||
          state.matchedLocation == '/register';
      if (auth is AuthLoading) return null; // wait
      if (auth is AuthUnauthenticated || auth is AuthError) {
        return isAuthRoute ? null : '/login';
      }
      if (auth is AuthAuthenticated) {
        return isAuthRoute ? '/home' : null;
      }
      return null;
    },
    refreshListenable: _RouterRefreshNotifier(ref),
    routes: [
      GoRoute(path: '/login', builder: (_, __) => const LoginPage()),
      GoRoute(path: '/register', builder: (_, __) => const RegisterPage()),
      GoRoute(path: '/home', builder: (_, __) => const HomePage()),
      GoRoute(path: '/profile', builder: (_, __) => const ProfilePage()),
      GoRoute(path: '/settings', builder: (_, __) => const SettingsPage()),
    ],
  );
});

class _RouterRefreshNotifier extends ChangeNotifier {
  _RouterRefreshNotifier(Ref ref) {
    ref.listen<AuthState>(authProvider, (_, __) => notifyListeners());
  }
}
```

- [ ] **Step 2: Verify analyze (will warn about missing pages — that's expected, they're created in Tasks 28-31)**

```bash
flutter analyze lib/router.dart
```

Expected: errors about missing imports for `LoginPage`, `RegisterPage`, etc. We'll resolve them in subsequent tasks. Skip for now.

- [ ] **Step 3: Commit**

```bash
git add lib/router.dart
git commit -m "routing: go_router with authProvider-driven redirect (pages stubbed in next tasks)"
```

---

### Task 27: `main.dart` + `app.dart`

**Files:**
- Create: `lib/main.dart`
- Create: `lib/app.dart`

- [ ] **Step 1: Write `main.dart`**

```dart
// lib/main.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';

void main() {
  runApp(const ProviderScope(child: StreamloadApp()));
}
```

- [ ] **Step 2: Write `app.dart`**

```dart
// lib/app.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'presentation/theme/theme.dart';
import 'router.dart';
import 'state/auth_provider.dart';

class StreamloadApp extends ConsumerStatefulWidget {
  const StreamloadApp({super.key});

  @override
  ConsumerState<StreamloadApp> createState() => _StreamloadAppState();
}

class _StreamloadAppState extends ConsumerState<StreamloadApp> {
  @override
  void initState() {
    super.initState();
    // Kick off bootstrap so the redirect logic in router has a real state.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(authProvider.notifier).bootstrap();
    });
  }

  @override
  Widget build(BuildContext context) {
    final router = ref.watch(routerProvider);
    return MaterialApp.router(
      title: 'Streamload',
      theme: streamloadTheme(),
      darkTheme: streamloadTheme(),
      themeMode: ThemeMode.dark,
      routerConfig: router,
      debugShowCheckedModeBanner: false,
    );
  }
}
```

- [ ] **Step 3: Verify analyze (still has missing-page errors — fine for now)**

```bash
flutter analyze lib/main.dart lib/app.dart
```

Expected: errors only from the pages that don't exist yet.

- [ ] **Step 4: Commit**

```bash
git add lib/main.dart lib/app.dart
git commit -m "app: main + StreamloadApp wiring (ProviderScope + router + theme)"
```

---

### Task 28: Login page

**Files:**
- Create: `lib/presentation/pages/login_page.dart`
- Create: `test/pages/login_page_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/pages/login_page_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/auth_api.dart';
import 'package:streamload_client/domain/models/user.dart';
import 'package:streamload_client/presentation/pages/login_page.dart';
import 'package:streamload_client/presentation/theme/theme.dart';
import 'package:streamload_client/state/api_client_provider.dart';

class _AuthApiMock extends Mock implements AuthApi {}

void main() {
  testWidgets('login form submits and calls AuthApi.login', (tester) async {
    final api = _AuthApiMock();
    when(() => api.login(username: 'alice', password: 'pw'))
        .thenAnswer((_) async => const User(
              id: 'u1', username: 'alice', email: 'a@x.com',
              emailVerified: true, role: 'user',
            ));

    await tester.pumpWidget(ProviderScope(
      overrides: [authApiProvider.overrideWith((_) async => api)],
      child: MaterialApp(theme: streamloadTheme(), home: const LoginPage()),
    ));
    await tester.enterText(find.byKey(const Key('login.username')), 'alice');
    await tester.enterText(find.byKey(const Key('login.password')), 'pw');
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pump();

    verify(() => api.login(username: 'alice', password: 'pw')).called(1);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/pages/login_page_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement LoginPage**

```dart
// lib/presentation/pages/login_page.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../state/auth_provider.dart';
import '../theme/colors.dart';
import '../theme/typography.dart';
import '../widgets/eyebrow.dart';
import '../widgets/primary_button.dart';
import '../widgets/streamload_text_field.dart';

class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});

  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final _username = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(authProvider.notifier).login(
            username: _username.text.trim(),
            password: _password.text,
          );
      if (mounted) context.go('/home');
    } catch (e) {
      setState(() => _error = 'Credenziali non valide');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Eyebrow('Cinema privato'),
                const SizedBox(height: 8),
                Text(
                  'Streamload',
                  style: StreamloadTypography.display(fontSize: 56),
                ),
                const SizedBox(height: 8),
                Text(
                  'Bentornato. Accedi per riprendere a guardare.',
                  style: StreamloadTypography.body(
                    fontSize: 14,
                    color: StreamloadColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 32),
                StreamloadTextField(
                  key: const Key('login.username'),
                  controller: _username,
                  label: 'Username o email',
                  autofocus: true,
                ),
                const SizedBox(height: 16),
                StreamloadTextField(
                  key: const Key('login.password'),
                  controller: _password,
                  label: 'Password',
                  obscure: true,
                  onSubmitted: (_) => _submit(),
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
                  key: const Key('login.submit'),
                  label: _busy ? 'Accesso…' : 'Accedi',
                  busy: _busy,
                  onPressed: _busy ? null : _submit,
                ),
                const SizedBox(height: 16),
                Center(
                  child: TextButton(
                    onPressed: () => context.go('/register'),
                    child: Text(
                      'Crea un account',
                      style: StreamloadTypography.body(
                        fontSize: 13,
                        color: StreamloadColors.accent,
                      ),
                    ),
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

- [ ] **Step 4: Run, expect pass**

```bash
flutter test test/pages/login_page_test.dart
```

Expected: 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add lib/presentation/pages/login_page.dart test/pages/login_page_test.dart
git commit -m "pages: LoginPage (form + AuthNotifier wiring)"
```

---

### Task 29: Register page

**Files:**
- Create: `lib/presentation/pages/register_page.dart`
- Create: `test/pages/register_page_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/pages/register_page_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/auth_api.dart';
import 'package:streamload_client/domain/models/user.dart';
import 'package:streamload_client/presentation/pages/register_page.dart';
import 'package:streamload_client/presentation/theme/theme.dart';
import 'package:streamload_client/state/api_client_provider.dart';

class _AuthApiMock extends Mock implements AuthApi {}

void main() {
  testWidgets('register form submits and calls AuthApi.register', (tester) async {
    final api = _AuthApiMock();
    when(() => api.register(
          username: 'bob', email: 'b@x.com', password: 'pw1234567',
        )).thenAnswer((_) async => const User(
              id: 'u2', username: 'bob', email: 'b@x.com',
              emailVerified: true, role: 'user',
            ));

    await tester.pumpWidget(ProviderScope(
      overrides: [authApiProvider.overrideWith((_) async => api)],
      child: MaterialApp(theme: streamloadTheme(), home: const RegisterPage()),
    ));
    await tester.enterText(find.byKey(const Key('register.username')), 'bob');
    await tester.enterText(find.byKey(const Key('register.email')), 'b@x.com');
    await tester.enterText(find.byKey(const Key('register.password')), 'pw1234567');
    await tester.tap(find.byKey(const Key('register.submit')));
    await tester.pump();

    verify(() => api.register(
          username: 'bob', email: 'b@x.com', password: 'pw1234567',
        )).called(1);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/pages/register_page_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement RegisterPage**

```dart
// lib/presentation/pages/register_page.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../state/auth_provider.dart';
import '../theme/colors.dart';
import '../theme/typography.dart';
import '../widgets/eyebrow.dart';
import '../widgets/primary_button.dart';
import '../widgets/streamload_text_field.dart';

class RegisterPage extends ConsumerStatefulWidget {
  const RegisterPage({super.key});

  @override
  ConsumerState<RegisterPage> createState() => _RegisterPageState();
}

class _RegisterPageState extends ConsumerState<RegisterPage> {
  final _username = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _username.dispose();
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(authProvider.notifier).register(
            username: _username.text.trim(),
            email: _email.text.trim(),
            password: _password.text,
          );
      if (mounted) context.go('/home');
    } catch (e) {
      setState(() => _error = 'Registrazione fallita. Controlla i dati e riprova.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Eyebrow('Nuovo accesso'),
                const SizedBox(height: 8),
                Text(
                  'Crea il tuo account',
                  style: StreamloadTypography.display(fontSize: 40),
                ),
                const SizedBox(height: 32),
                StreamloadTextField(
                  key: const Key('register.username'),
                  controller: _username,
                  label: 'Username',
                  autofocus: true,
                ),
                const SizedBox(height: 16),
                StreamloadTextField(
                  key: const Key('register.email'),
                  controller: _email,
                  label: 'Email',
                  keyboardType: TextInputType.emailAddress,
                ),
                const SizedBox(height: 16),
                StreamloadTextField(
                  key: const Key('register.password'),
                  controller: _password,
                  label: 'Password',
                  obscure: true,
                  onSubmitted: (_) => _submit(),
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
                  key: const Key('register.submit'),
                  label: _busy ? 'Creazione…' : 'Crea account',
                  busy: _busy,
                  onPressed: _busy ? null : _submit,
                ),
                const SizedBox(height: 16),
                Center(
                  child: TextButton(
                    onPressed: () => context.go('/login'),
                    child: Text(
                      'Hai già un account? Accedi',
                      style: StreamloadTypography.body(
                        fontSize: 13,
                        color: StreamloadColors.accent,
                      ),
                    ),
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

- [ ] **Step 4: Run, expect pass**

```bash
flutter test test/pages/register_page_test.dart
```

Expected: 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add lib/presentation/pages/register_page.dart test/pages/register_page_test.dart
git commit -m "pages: RegisterPage (form + AuthNotifier wiring)"
```

---

### Task 30: Home placeholder + Profile pages

**Files:**
- Create: `lib/presentation/pages/home_page.dart`
- Create: `lib/presentation/pages/profile_page.dart`

- [ ] **Step 1: Write `home_page.dart`**

```dart
// lib/presentation/pages/home_page.dart
//
// PLACEHOLDER. Real home (rows of poster cards from collections) is sub-plan #6.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../state/auth_provider.dart';
import '../theme/colors.dart';
import '../theme/typography.dart';
import '../widgets/eyebrow.dart';

class HomePage extends ConsumerWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    final username = switch (auth) {
      AuthAuthenticated(:final user) => user.username,
      _ => 'guest',
    };

    return Scaffold(
      appBar: AppBar(
        title: Text(
          'Streamload',
          style: StreamloadTypography.display(fontSize: 22),
        ),
        actions: [
          IconButton(
            tooltip: 'Impostazioni',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => context.go('/settings'),
          ),
          IconButton(
            tooltip: 'Profilo',
            icon: const Icon(Icons.person_outline),
            onPressed: () => context.go('/profile'),
          ),
        ],
      ),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Eyebrow('Benvenuto'),
            const SizedBox(height: 8),
            Text(
              username,
              style: StreamloadTypography.display(fontSize: 64),
            ),
            const SizedBox(height: 24),
            Text(
              'Il catalogo arriva nei prossimi rilasci.',
              style: StreamloadTypography.body(
                fontSize: 14,
                color: StreamloadColors.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
```

- [ ] **Step 2: Write `profile_page.dart`**

```dart
// lib/presentation/pages/profile_page.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../state/auth_provider.dart';
import '../theme/colors.dart';
import '../theme/typography.dart';
import '../widgets/eyebrow.dart';
import '../widgets/primary_button.dart';

class ProfilePage extends ConsumerWidget {
  const ProfilePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    final user = switch (auth) {
      AuthAuthenticated(:final user) => user,
      _ => null,
    };

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/home'),
        ),
        title: const Text('Profilo'),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              children: [
                const Eyebrow('Account'),
                const SizedBox(height: 16),
                Text('Username',
                    style: StreamloadTypography.mono(fontSize: 11)),
                Text(user?.username ?? '—',
                    style: StreamloadTypography.body(fontSize: 18)),
                const SizedBox(height: 16),
                Text('Email',
                    style: StreamloadTypography.mono(fontSize: 11)),
                Text(user?.email ?? '—',
                    style: StreamloadTypography.body(fontSize: 14)),
                const SizedBox(height: 16),
                Text('Ruolo',
                    style: StreamloadTypography.mono(fontSize: 11)),
                Text(user?.role ?? '—',
                    style: StreamloadTypography.body(
                      fontSize: 14,
                      color: user?.role == 'admin'
                          ? StreamloadColors.accent
                          : StreamloadColors.textSecondary,
                    )),
                const SizedBox(height: 32),
                PrimaryButton(
                  label: 'Esci',
                  onPressed: () async {
                    await ref.read(authProvider.notifier).logout();
                    if (context.mounted) context.go('/login');
                  },
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

- [ ] **Step 3: Verify analyze (router.dart should now resolve)**

```bash
flutter analyze
```

Expected: no errors. May still flag pages we haven't created yet (settings_page in Task 31).

- [ ] **Step 4: Commit**

```bash
git add lib/presentation/pages/home_page.dart lib/presentation/pages/profile_page.dart
git commit -m "pages: HomePage placeholder + ProfilePage with logout"
```

---

## Phase H — Settings page

### Task 31: Settings page

**Files:**
- Create: `lib/presentation/pages/settings_page.dart`
- Create: `test/pages/settings_page_test.dart`

- [ ] **Step 1: Write the failing test FIRST**

```dart
// test/pages/settings_page_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/settings_api.dart';
import 'package:streamload_client/domain/models/settings.dart';
import 'package:streamload_client/presentation/pages/settings_page.dart';
import 'package:streamload_client/presentation/theme/theme.dart';
import 'package:streamload_client/state/api_client_provider.dart';

class _SettingsApiMock extends Mock implements SettingsApi {}

void main() {
  setUpAll(() => registerFallbackValue(const UserSettingsModel()));

  testWidgets('renders current settings and saves on submit', (tester) async {
    final api = _SettingsApiMock();
    when(api.get).thenAnswer((_) async =>
        const UserSettingsModel(theme: 'dark', audioPrefLang: 'eng'));
    when(() => api.update(any())).thenAnswer((inv) async =>
        inv.positionalArguments.first as UserSettingsModel);

    await tester.pumpWidget(ProviderScope(
      overrides: [settingsApiProvider.overrideWith((_) async => api)],
      child: MaterialApp(theme: streamloadTheme(), home: const SettingsPage()),
    ));
    // Wait for the FutureBuilder to resolve
    await tester.pumpAndSettle();

    expect(find.text('eng'), findsOneWidget); // audio_pref_lang shown
    await tester.tap(find.byKey(const Key('settings.save')));
    await tester.pump();

    verify(() => api.update(any())).called(1);
  });
}
```

- [ ] **Step 2: Run, expect failure**

```bash
flutter test test/pages/settings_page_test.dart
```

Expected: import error.

- [ ] **Step 3: Implement SettingsPage**

```dart
// lib/presentation/pages/settings_page.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../domain/models/settings.dart';
import '../../state/settings_provider.dart';
import '../theme/colors.dart';
import '../theme/typography.dart';
import '../widgets/eyebrow.dart';
import '../widgets/primary_button.dart';

class SettingsPage extends ConsumerStatefulWidget {
  const SettingsPage({super.key});

  @override
  ConsumerState<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends ConsumerState<SettingsPage> {
  UserSettingsModel? _draft;
  bool _busy = false;

  Future<void> _save() async {
    if (_draft == null) return;
    setState(() => _busy = true);
    try {
      await ref.read(settingsControllerProvider.notifier).save(_draft!);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Impostazioni salvate')),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(settingsControllerProvider);

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/home'),
        ),
        title: const Text('Impostazioni'),
      ),
      body: state.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Text('Errore: $e',
              style: StreamloadTypography.body(
                fontSize: 14,
                color: StreamloadColors.critical,
              )),
        ),
        data: (settings) {
          _draft ??= settings;
          return ListView(
            padding: const EdgeInsets.all(32),
            children: [
              const Eyebrow('Riproduzione'),
              const SizedBox(height: 12),
              _languageRow(
                label: 'Audio preferito',
                value: _draft!.audioPrefLang,
                onChanged: (v) => setState(() =>
                    _draft = _draft!.copyWith(audioPrefLang: v)),
              ),
              _languageRow(
                label: 'Sottotitoli preferiti',
                value: _draft!.subsPrefLang,
                onChanged: (v) => setState(() =>
                    _draft = _draft!.copyWith(subsPrefLang: v)),
              ),
              _qualityRow(),
              SwitchListTile(
                title: const Text('Auto-play episodio successivo'),
                value: _draft!.autoplayNextEpisode,
                onChanged: (v) => setState(() =>
                    _draft = _draft!.copyWith(autoplayNextEpisode: v)),
              ),
              SwitchListTile(
                title: const Text('Salta sigla automaticamente'),
                value: _draft!.skipIntro,
                onChanged: (v) => setState(() =>
                    _draft = _draft!.copyWith(skipIntro: v)),
              ),
              const SizedBox(height: 24),
              const Eyebrow('Aspetto'),
              const SizedBox(height: 12),
              _themeRow(),
              const SizedBox(height: 32),
              PrimaryButton(
                key: const Key('settings.save'),
                label: _busy ? 'Salvataggio…' : 'Salva',
                busy: _busy,
                onPressed: _busy ? null : _save,
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _languageRow({
    required String label,
    required String value,
    required ValueChanged<String> onChanged,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(child: Text(label,
              style: StreamloadTypography.body(fontSize: 14))),
          DropdownButton<String>(
            value: value,
            items: const [
              DropdownMenuItem(value: 'ita', child: Text('ita')),
              DropdownMenuItem(value: 'eng', child: Text('eng')),
              DropdownMenuItem(value: 'jpn', child: Text('jpn')),
            ],
            onChanged: (v) => v != null ? onChanged(v) : null,
          ),
        ],
      ),
    );
  }

  Widget _qualityRow() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(child: Text('Qualità massima',
              style: StreamloadTypography.body(fontSize: 14))),
          DropdownButton<int?>(
            value: _draft!.qualityCapHeight,
            items: const [
              DropdownMenuItem(value: null, child: Text('senza limite')),
              DropdownMenuItem(value: 480, child: Text('480p')),
              DropdownMenuItem(value: 720, child: Text('720p')),
              DropdownMenuItem(value: 1080, child: Text('1080p')),
              DropdownMenuItem(value: 2160, child: Text('2160p')),
            ],
            onChanged: (v) => setState(() =>
                _draft = _draft!.copyWith(qualityCapHeight: v)),
          ),
        ],
      ),
    );
  }

  Widget _themeRow() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(child: Text('Tema',
              style: StreamloadTypography.body(fontSize: 14))),
          DropdownButton<String>(
            value: _draft!.theme,
            items: const [
              DropdownMenuItem(value: 'auto', child: Text('Automatico')),
              DropdownMenuItem(value: 'light', child: Text('Chiaro')),
              DropdownMenuItem(value: 'dark', child: Text('Scuro')),
            ],
            onChanged: (v) => v != null
                ? setState(() => _draft = _draft!.copyWith(theme: v))
                : null,
          ),
        ],
      ),
    );
  }
}
```

- [ ] **Step 4: Run, expect pass**

```bash
flutter test test/pages/settings_page_test.dart
```

Expected: 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add lib/presentation/pages/settings_page.dart test/pages/settings_page_test.dart
git commit -m "pages: SettingsPage bound to /api/settings GET/PUT"
```

---

## Phase I — CI + smoke

### Task 32: GitHub Actions test workflow

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: Test

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4

      - name: Set up Flutter
        uses: subosito/flutter-action@v2
        with:
          channel: stable
          flutter-version: '3.41.x'

      - name: Show versions
        run: |
          flutter --version
          dart --version

      - name: Resolve deps
        run: flutter pub get

      - name: Generate code
        run: dart run build_runner build --delete-conflicting-outputs

      - name: Analyze
        run: flutter analyze --fatal-infos

      - name: Test
        run: flutter test --reporter expanded
```

- [ ] **Step 2: Commit + push and watch the first CI run**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
git add .github/workflows/test.yml
git commit -m "ci: flutter test + analyze on push/PR (macos-14 runner)"
git push origin main
```

- [ ] **Step 3: Watch the workflow run**

```bash
sleep 10
gh run list --limit 2 --repo alfanowski/Streamload-Client
```

Expected: a run named `Test` for the latest commit. Wait for it to complete:

```bash
gh run watch $(gh run list --limit 1 --repo alfanowski/Streamload-Client --json databaseId --jq '.[0].databaseId')
```

Expected: completes with `success`.

---

### Task 33: Manual end-to-end smoke against the v0.3.0 backend

**Files:** none (validation only).

- [ ] **Step 1: Confirm backend is running**

In a separate terminal:

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload
set -a; source .env; set +a
venv/bin/python streamload.py --api &
```

Wait ~5 seconds, then verify:

```bash
curl -s http://127.0.0.1:8000/api/health
```

Expected: `{"status":"ok","version":"0.3.0"}`.

- [ ] **Step 2: Run the Flutter app on macOS**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
flutter run -d macos
```

Expected: app builds, opens a window, shows the LoginPage with "Streamload" in serif italic.

- [ ] **Step 3: Login as the bootstrap admin**

In the app, type:
- Username: `alfanowski`
- Password: `Test12345Test` (or whatever your `.env` STREAMLOAD_ADMIN_PASSWORD says)

Click **Accedi**.

Expected: navigates to `/home`, shows `alfanowski` as the username.

- [ ] **Step 4: Open settings, change theme, save**

Click the gear icon → drop "Tema" to `Scuro` → click **Salva**.

Expected: snackbar `Impostazioni salvate`.

Confirm server-side persistence:

```bash
curl -s -c /tmp/c.txt -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alfanowski","password":"Test12345Test"}' > /dev/null
curl -s -b /tmp/c.txt http://127.0.0.1:8000/api/settings | python3 -m json.tool
```

Expected: response shows `"theme": "dark"`.

- [ ] **Step 5: Quit the app, restart it — confirm session survives**

Close the app window. Re-run `flutter run -d macos`. Expected: app boots, skips login, lands directly on `/home` (cookie jar restored from disk).

- [ ] **Step 6: Logout from /profile**

Click person icon → **Esci**. Expected: returns to LoginPage.

- [ ] **Step 7: Done — restart shows login again**

Re-run `flutter run -d macos`. Expected: LoginPage (cookie cleared).

- [ ] **Step 8: Stop the backend**

```bash
pkill -9 -f granian 2>/dev/null
```

- [ ] **Step 9: Final test suite green**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload-Client
flutter test
```

Expected: all tests pass with 0 failures.

---

## Plan complete

After Task 33 you have:

- A new public GitHub repo `alfanowski/Streamload-Client` with green CI.
- A Flutter macOS app that boots, persists session via Keychain-backed cookie jar, authenticates against the v0.3.0 backend, lets the user manage account settings, and lays out the database schema for everything sub-plans #4-#6 will need.
- A typed ApiClient covering every reduced-backend endpoint, ready to be consumed by the catalog/search/title/watch screens added in sub-plan #6.
- A theme module + reusable widgets matching the v2 web's Cinematic Editorial aesthetic, ready to drape over the real catalog UI when it lands.

What's deliberately NOT here (and why):

- **Plugin runtime** — sub-plan #4 builds the QuickJS sandbox + registry loader + sha256-verified updater on top of `streamload-plugins` (already shipped in plan #2). That work depends on the empty drift tables we just created (`installed_plugins`, `plugin_kv`, `catalog_sources`).
- **HLS playback + media_kit + local proxy** — sub-plan #5 adds the streaming layer. It assumes drift's `catalog_sources` already exists (it does, from this plan) and that the plugin runtime can answer `getStreams()` (sub-plan #4).
- **Real catalog UI** (rows, posters, search, title detail, watch, admin dashboard) — sub-plan #6 is the feature-parity push that consumes everything from #3, #4, #5.
- **Auto-updater** — wired in sub-plan #6 once we have a release pipeline worth updating from.
- **WebAuthn passkey biometric flow** — sub-plan #6 polish.
