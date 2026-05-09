# v3 Plugin Distribution Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the private `streamload-plugins` GitHub repo with a documented plugin contract, a JSON-Schema-validated registry, a deterministic fixture plugin for client tests, lint tooling, and a CI workflow that catches every operator footgun (missing sha256 bump, broken plugin, schema-invalid registry).

**Architecture:** A standalone repo at `/Users/alfanowski/Desktop/Projects/streamload-plugins/` (sibling to Streamload + Streamload-Web). Single-source-of-truth `registry.json` at the root lists every plugin with version, sha256, api_version, capabilities. End-user clients fetch the registry over the GitHub API with a per-user PAT, then download each plugin file and verify its sha256 before mounting it in the QuickJS sandbox. Lint CI (Node.js) runs on every push to enforce the contract. No code on the operator's VPS.

**Tech Stack:** GitHub (private repo + Actions), Node.js 20+ (lint script + ajv-cli), JSON Schema draft-07, JavaScript ESM (plugin format), Bash (sha256 helper).

---

## Source spec

This plan implements **Sub-plan #2** from `docs/superpowers/specs/2026-05-09-streamload-v3-design.md` §17.

The Streamload-Client (sub-plan #3+) will consume this repo via per-user PAT. This plan delivers the contract + tooling; it does NOT implement the client side of the loader.

## File structure

All paths relative to the new repo root `/Users/alfanowski/Desktop/Projects/streamload-plugins/`.

| Path | Responsibility |
|---|---|
| `README.md` | Reader-facing overview: what this repo is, who can read it, how operator publishes, how end-user installs. |
| `registry.json` | Machine-readable manifest. The single source of truth for which plugin files exist + their versions + sha256s. |
| `plugins/_fixture/echo.js` | Deterministic test fixture used by Streamload-Client integration tests. NOT a real scraper. |
| `docs/plugin-contract.md` | TypeScript-style interface spec: `meta`, `search`, `getSeasons`, `getEpisodes`, `getStreams`, the `host.*` API surface, sandbox rules, versioning. |
| `docs/registry-schema.md` | JSON Schema (draft-07) for `registry.json` + 3 worked examples + the sha256 verification protocol. |
| `docs/operator-runbook.md` | "I want to add/update a plugin" step-by-step. |
| `docs/end-user-pat.md` | "How to mint and distribute a per-user PAT". Fine-grained-first, classic fallback. |
| `tools/sha256.sh` | One-liner helper: `tools/sha256.sh plugins/foo.js` → 64-char hex on stdout. |
| `tools/lint-plugin.mjs` | Node ESM script. Validates one plugin file's `meta` + exports against the contract. Exit 0 pass / 1 fail. |
| `tools/check-registry.mjs` | Node ESM script. Validates `registry.json` against the JSON Schema AND verifies every entry's `sha256` matches the on-disk file. |
| `schemas/registry.schema.json` | The JSON Schema referenced by `tools/check-registry.mjs` and `docs/registry-schema.md`. |
| `package.json` | Pins `ajv` + `ajv-formats` for the lint scripts. No app code; this is a tooling-only package.json. |
| `.github/workflows/lint.yml` | CI: runs `tools/lint-plugin.mjs` on every plugin file + `tools/check-registry.mjs` on the registry. |
| `.gitignore` | `node_modules/`, OS clutter. |

After this plan ships, the directory tree is exactly the above, plus `.git/` and `node_modules/` (untracked). 14 tracked files total.

---

## Phase A — Local repo scaffolding

### Task 1: Create the local directory + initialize git

**Files:**
- Create: `/Users/alfanowski/Desktop/Projects/streamload-plugins/` (directory)
- Create: `/Users/alfanowski/Desktop/Projects/streamload-plugins/.gitignore`

- [ ] **Step 1: Create the directory and initialize git**

```bash
mkdir -p /Users/alfanowski/Desktop/Projects/streamload-plugins
cd /Users/alfanowski/Desktop/Projects/streamload-plugins
git init -b main
```

Expected: `Initialized empty Git repository in …/streamload-plugins/.git/`.

- [ ] **Step 2: Write `.gitignore`**

```
node_modules/
.DS_Store
*.log
.env
.env.local
.idea/
.vscode/
```

- [ ] **Step 3: Stage + commit**

```bash
cd /Users/alfanowski/Desktop/Projects/streamload-plugins
git add .gitignore
git commit -m "chore: initial commit — gitignore for tooling clutter"
```

Expected: `[main (root-commit) <sha>] chore: initial commit — gitignore for tooling clutter`.

---

### Task 2: Create the GitHub private repo and link the remote

**Files:** none (remote operation).

- [ ] **Step 1: Verify gh CLI is logged in as alfanowski**

```bash
gh auth status 2>&1 | head -5
```

Expected output contains `Logged in to github.com account alfanowski`.

- [ ] **Step 2: Create the private repo**

```bash
gh repo create alfanowski/streamload-plugins \
  --private \
  --description "Streamload v3 scraping plugins (private)" \
  --disable-issues=false \
  --disable-wiki
```

Expected: `https://github.com/alfanowski/streamload-plugins` printed.

- [ ] **Step 3: Add the remote and push**

```bash
cd /Users/alfanowski/Desktop/Projects/streamload-plugins
git remote add origin https://github.com/alfanowski/streamload-plugins.git
git push -u origin main
```

Expected: `Branch 'main' set up to track remote branch 'main' from 'origin'.`

- [ ] **Step 4: Verify visibility on GitHub**

```bash
gh repo view alfanowski/streamload-plugins --json visibility,name,description
```

Expected: `{"visibility":"PRIVATE","name":"streamload-plugins","description":"Streamload v3 scraping plugins (private)"}`.

---

### Task 3: Initialize package.json + install lint dependencies

**Files:**
- Create: `package.json`

- [ ] **Step 1: Write `package.json`**

```json
{
  "name": "streamload-plugins-tooling",
  "version": "0.1.0",
  "description": "Lint + schema-validation tooling for Streamload v3 plugins.",
  "private": true,
  "type": "module",
  "scripts": {
    "lint:plugin": "node tools/lint-plugin.mjs",
    "lint:registry": "node tools/check-registry.mjs",
    "lint:all": "for f in plugins/*.js plugins/**/*.js; do node tools/lint-plugin.mjs \"$f\" || exit 1; done && node tools/check-registry.mjs"
  },
  "engines": {
    "node": ">=20"
  },
  "dependencies": {
    "ajv": "^8.17.1",
    "ajv-formats": "^3.0.1"
  }
}
```

- [ ] **Step 2: Install + commit lockfile**

```bash
cd /Users/alfanowski/Desktop/Projects/streamload-plugins
npm install
```

Expected: `package-lock.json` created, `node_modules/` populated, no errors.

- [ ] **Step 3: Commit**

```bash
git add package.json package-lock.json
git commit -m "chore: pin ajv + ajv-formats for plugin/registry linting"
```

---

## Phase B — Schema, contract, registry skeleton

### Task 4: JSON Schema for `registry.json`

**Files:**
- Create: `schemas/registry.schema.json`

- [ ] **Step 1: Write the schema**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://github.com/alfanowski/streamload-plugins/schemas/registry.schema.json",
  "title": "Streamload Plugin Registry",
  "type": "object",
  "required": ["format_version", "updated_at", "plugins"],
  "additionalProperties": false,
  "properties": {
    "format_version": {
      "type": "integer",
      "const": 1,
      "description": "Bumped only on breaking changes to the registry format itself."
    },
    "updated_at": {
      "type": "string",
      "format": "date-time",
      "description": "ISO-8601 UTC timestamp of the last edit."
    },
    "plugins": {
      "type": "array",
      "items": { "$ref": "#/definitions/PluginEntry" }
    }
  },
  "definitions": {
    "PluginEntry": {
      "type": "object",
      "required": ["short_name", "file", "version", "api_version", "sha256", "capabilities"],
      "additionalProperties": false,
      "properties": {
        "short_name": {
          "type": "string",
          "pattern": "^[a-z][a-z0-9_]{1,15}$",
          "description": "Stable identifier used by the client to address this plugin. lowercase, snake_case, 2-16 chars."
        },
        "file": {
          "type": "string",
          "pattern": "^plugins/[A-Za-z0-9_/-]+\\.js$",
          "description": "Path to the plugin file relative to the repo root."
        },
        "version": {
          "type": "string",
          "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+(-[A-Za-z0-9.-]+)?$",
          "description": "Semver. Bumped per content change."
        },
        "api_version": {
          "type": "integer",
          "minimum": 1,
          "description": "Host API contract version. Currently 1."
        },
        "sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "description": "Lowercase hex sha256 of the file as committed."
        },
        "min_app_version": {
          "type": "string",
          "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$",
          "description": "Optional. If present, clients below this app version skip this plugin."
        },
        "capabilities": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "string",
            "enum": [
              "movie",
              "movie:anime",
              "movie:kids",
              "movie:documentary",
              "tv",
              "tv:anime",
              "tv:kids",
              "tv:documentary",
              "tv:reality",
              "tv:news",
              "tv:sport"
            ]
          }
        }
      }
    }
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add schemas/registry.schema.json
git commit -m "feat(schema): JSON Schema for registry.json"
```

---

### Task 5: Initial `registry.json` containing only the fixture entry

**Files:**
- Create: `registry.json`

The fixture file's actual sha256 will be filled in by Task 6 (after the file exists). For now we use a placeholder that the lint will reject — confirms the lint catches this case.

- [ ] **Step 1: Write registry.json with a known-bad sha256 for the fixture**

The fixture file doesn't exist yet (Task 6 creates it). We seed registry.json with `0000…0000` so lint rejects it. We'll fix in Task 6.

```json
{
  "format_version": 1,
  "updated_at": "2026-05-10T00:00:00Z",
  "plugins": [
    {
      "short_name": "echo",
      "file": "plugins/_fixture/echo.js",
      "version": "1.0.0",
      "api_version": 1,
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "capabilities": ["movie"]
    }
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add registry.json
git commit -m "feat(registry): scaffold registry.json with fixture entry (sha256 pending)"
```

---

## Phase C — Lint tooling (TDD: write the tests by way of the linters' own behaviour)

### Task 6: `tools/sha256.sh` — file hash helper

**Files:**
- Create: `tools/sha256.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Compute the lowercase hex sha256 of a file. Used when bumping registry.json.
#
# Usage: tools/sha256.sh plugins/_fixture/echo.js
#        → e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <file>" >&2
  exit 2
fi

if [[ ! -f "$1" ]]; then
  echo "error: $1 is not a regular file" >&2
  exit 2
fi

# macOS has shasum; Linux usually has sha256sum. Prefer shasum for portability.
if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$1" | awk '{print $1}'
else
  sha256sum "$1" | awk '{print $1}'
fi
```

- [ ] **Step 2: Make executable**

```bash
chmod +x tools/sha256.sh
```

- [ ] **Step 3: Verify it works against any file (use package.json as a proof point)**

```bash
cd /Users/alfanowski/Desktop/Projects/streamload-plugins
./tools/sha256.sh package.json
```

Expected: a 64-char hex string. Length check:

```bash
test "$(./tools/sha256.sh package.json | wc -c | awk '{print $1}')" = "65"  # 64 hex + newline
echo "length OK"
```

Expected: `length OK`.

- [ ] **Step 4: Commit**

```bash
git add tools/sha256.sh
git commit -m "feat(tools): sha256.sh helper for registry hash bumps"
```

---

### Task 7: `plugins/_fixture/echo.js` fixture plugin

**Files:**
- Create: `plugins/_fixture/echo.js`

- [ ] **Step 1: Write the fixture**

```js
// Echo — deterministic test fixture for Streamload-Client integration tests.
// NOT a real scraper. Returns a static synthetic shape that callers can assert
// against. No network calls, no host.http usage, no upstream side effects.

export const meta = {
  short_name: "echo",
  display_name: "Echo (test fixture)",
  version: "1.0.0",
  api_version: 1,
  capabilities: ["movie"],
};

export async function search(query) {
  return [
    {
      id: "echo-1",
      title: query,
      url: `https://example.invalid/title/${encodeURIComponent(query)}`,
      type: "movie",
      service: "echo",
      year: null,
      genre: null,
      image_url: null,
      description: null,
    },
  ];
}

export async function getSeasons(_entry) {
  return [];
}

export async function getEpisodes(_season) {
  return [];
}

export async function getStreams(entry) {
  return {
    manifest_url: "https://example.invalid/master.m3u8",
    headers: { "X-Echo-Title": entry.title ?? "" },
    is_drm: false,
    drm_keys: null,
  };
}
```

- [ ] **Step 2: Compute its sha256 + update registry.json**

```bash
cd /Users/alfanowski/Desktop/Projects/streamload-plugins
HASH=$(./tools/sha256.sh plugins/_fixture/echo.js)
echo "fixture sha256: $HASH"
```

Expected: 64-char hex.

Now edit `registry.json` and replace the `0000…0000` sha256 with `$HASH`. Concretely:

```bash
python3 -c "
import json, sys, subprocess
h = subprocess.check_output(['./tools/sha256.sh', 'plugins/_fixture/echo.js']).decode().strip()
with open('registry.json') as f: d = json.load(f)
d['plugins'][0]['sha256'] = h
with open('registry.json', 'w') as f: json.dump(d, f, indent=2); f.write('\n')
print('registry.json updated, sha256:', h)
"
```

Expected: `registry.json updated, sha256: <64-char-hex>`.

Verify the file:

```bash
grep sha256 registry.json
```

Expected: the hex string from above.

- [ ] **Step 3: Commit both files together**

```bash
git add plugins/_fixture/echo.js registry.json
git commit -m "feat(fixture): echo plugin + matching sha256 in registry"
```

---

### Task 8: `tools/lint-plugin.mjs` — single-plugin contract validator

**Files:**
- Create: `tools/lint-plugin.mjs`

- [ ] **Step 1: Write the linter**

```js
#!/usr/bin/env node
// Validate a single plugin file against the v3 contract.
//
// Usage: node tools/lint-plugin.mjs plugins/_fixture/echo.js
//
// Exit codes:
//   0  pass
//   1  fail (with diagnostic on stderr)
//   2  usage error

import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import { existsSync } from "node:fs";

const ALLOWED_CAPABILITIES = new Set([
  "movie",
  "movie:anime",
  "movie:kids",
  "movie:documentary",
  "tv",
  "tv:anime",
  "tv:kids",
  "tv:documentary",
  "tv:reality",
  "tv:news",
  "tv:sport",
]);

const SHORT_NAME_RE = /^[a-z][a-z0-9_]{1,15}$/;
const SEMVER_RE = /^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$/;
const REQUIRED_FUNCS = ["search", "getSeasons", "getEpisodes", "getStreams"];

function fail(msg) {
  console.error(`✗ ${msg}`);
  process.exit(1);
}

function ok(msg) {
  console.log(`✓ ${msg}`);
}

async function main() {
  const arg = process.argv[2];
  if (!arg) {
    console.error("usage: node tools/lint-plugin.mjs <path-to-plugin.js>");
    process.exit(2);
  }
  const path = resolve(arg);
  if (!existsSync(path)) {
    console.error(`error: file not found: ${path}`);
    process.exit(2);
  }

  let mod;
  try {
    mod = await import(pathToFileURL(path).href);
  } catch (e) {
    fail(`cannot import: ${e.message}`);
  }

  // meta export
  if (!mod.meta || typeof mod.meta !== "object") {
    fail("missing or non-object `meta` export");
  }
  const m = mod.meta;

  for (const k of ["short_name", "display_name", "version", "api_version", "capabilities"]) {
    if (!(k in m)) fail(`meta.${k} missing`);
  }

  if (typeof m.short_name !== "string" || !SHORT_NAME_RE.test(m.short_name)) {
    fail(`meta.short_name must match ${SHORT_NAME_RE} (got ${JSON.stringify(m.short_name)})`);
  }
  if (typeof m.display_name !== "string" || m.display_name.length === 0) {
    fail("meta.display_name must be a non-empty string");
  }
  if (typeof m.version !== "string" || !SEMVER_RE.test(m.version)) {
    fail(`meta.version must be semver (got ${JSON.stringify(m.version)})`);
  }
  if (m.api_version !== 1) {
    fail(`meta.api_version must be 1 (got ${JSON.stringify(m.api_version)})`);
  }
  if (!Array.isArray(m.capabilities) || m.capabilities.length === 0) {
    fail("meta.capabilities must be a non-empty array");
  }
  for (const c of m.capabilities) {
    if (!ALLOWED_CAPABILITIES.has(c)) {
      fail(`meta.capabilities contains unknown value: ${JSON.stringify(c)}`);
    }
  }

  // optional min_app_version
  if ("min_app_version" in m) {
    if (typeof m.min_app_version !== "string" || !/^[0-9]+\.[0-9]+\.[0-9]+$/.test(m.min_app_version)) {
      fail(`meta.min_app_version must be MAJOR.MINOR.PATCH (got ${JSON.stringify(m.min_app_version)})`);
    }
  }

  // required functions
  for (const fn of REQUIRED_FUNCS) {
    if (typeof mod[fn] !== "function") {
      fail(`missing exported async function ${fn}()`);
    }
    if (mod[fn].constructor.name !== "AsyncFunction") {
      fail(`${fn} must be declared async`);
    }
  }

  ok(`${m.short_name}@${m.version} (api_version=${m.api_version}, capabilities=[${m.capabilities.join(",")}])`);
}

main().catch((e) => {
  console.error(`✗ lint crashed: ${e.stack || e.message}`);
  process.exit(1);
});
```

- [ ] **Step 2: Run against the fixture, expect pass**

```bash
cd /Users/alfanowski/Desktop/Projects/streamload-plugins
node tools/lint-plugin.mjs plugins/_fixture/echo.js
echo "exit=$?"
```

Expected:

```
✓ echo@1.0.0 (api_version=1, capabilities=[movie])
exit=0
```

- [ ] **Step 3: Smoke a failure path — write a temporary bad plugin and confirm exit=1**

```bash
cat > /tmp/bad-plugin.js <<'EOF'
export const meta = {
  short_name: "BAD-NAME",  // uppercase + dash — should be rejected
  display_name: "Bad",
  version: "not-a-semver",
  api_version: 2,
  capabilities: ["movie:made-up"],
};
export async function search() { return []; }
export async function getSeasons() { return []; }
export async function getEpisodes() { return []; }
export async function getStreams() { return {}; }
EOF
node tools/lint-plugin.mjs /tmp/bad-plugin.js
echo "exit=$?"
```

Expected: `✗ meta.short_name must match …` and `exit=1`.

Clean up:

```bash
rm /tmp/bad-plugin.js
```

- [ ] **Step 4: Commit**

```bash
git add tools/lint-plugin.mjs
git commit -m "feat(tools): lint-plugin.mjs — per-file contract validator"
```

---

### Task 9: `tools/check-registry.mjs` — schema + sha256 audit

**Files:**
- Create: `tools/check-registry.mjs`

- [ ] **Step 1: Write the audit script**

```js
#!/usr/bin/env node
// Validate registry.json:
//   1. structurally against schemas/registry.schema.json (JSON Schema)
//   2. every entry's sha256 matches the actual file on disk
//   3. every entry's `file` path exists
//
// Exit 0 pass / 1 fail.

import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import Ajv from "ajv";
import addFormats from "ajv-formats";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "..");

function fail(msg) {
  console.error(`✗ ${msg}`);
  process.exit(1);
}

function sha256OfFile(path) {
  const h = createHash("sha256");
  h.update(readFileSync(path));
  return h.digest("hex");
}

function main() {
  const registryPath = resolve(repoRoot, "registry.json");
  const schemaPath = resolve(repoRoot, "schemas/registry.schema.json");

  if (!existsSync(registryPath)) fail("registry.json missing");
  if (!existsSync(schemaPath)) fail("schemas/registry.schema.json missing");

  const registry = JSON.parse(readFileSync(registryPath, "utf-8"));
  const schema = JSON.parse(readFileSync(schemaPath, "utf-8"));

  const ajv = new Ajv({ allErrors: true, strict: false });
  addFormats(ajv);
  const validate = ajv.compile(schema);
  if (!validate(registry)) {
    for (const err of validate.errors) {
      console.error(`✗ schema: ${err.instancePath} ${err.message}`);
    }
    process.exit(1);
  }
  console.log(`✓ schema valid (${registry.plugins.length} plugin entries)`);

  // Per-entry checks
  for (const e of registry.plugins) {
    const filePath = resolve(repoRoot, e.file);
    if (!existsSync(filePath)) {
      fail(`${e.short_name}: file ${e.file} not found on disk`);
    }
    const actual = sha256OfFile(filePath);
    if (actual !== e.sha256) {
      fail(
        `${e.short_name}: sha256 mismatch (registry=${e.sha256.slice(0, 12)}…, disk=${actual.slice(0, 12)}…). ` +
        `Did you forget to run tools/sha256.sh after editing the file?`,
      );
    }
    console.log(`✓ ${e.short_name}@${e.version} — file + sha256 match`);
  }
}

main();
```

- [ ] **Step 2: Run against the live registry, expect pass**

```bash
cd /Users/alfanowski/Desktop/Projects/streamload-plugins
node tools/check-registry.mjs
echo "exit=$?"
```

Expected:

```
✓ schema valid (1 plugin entries)
✓ echo@1.0.0 — file + sha256 match
exit=0
```

- [ ] **Step 3: Smoke a failure — temporarily corrupt the registry sha256**

```bash
# Save original
cp registry.json /tmp/registry.json.bak
# Corrupt the sha256
python3 -c "
import json
with open('registry.json') as f: d = json.load(f)
d['plugins'][0]['sha256'] = 'a' * 64
with open('registry.json', 'w') as f: json.dump(d, f, indent=2); f.write('\n')
"
node tools/check-registry.mjs
echo "exit=$?"
# Restore
mv /tmp/registry.json.bak registry.json
```

Expected output includes `✗ echo: sha256 mismatch …` and `exit=1`. After restoring, re-run to confirm `exit=0` again:

```bash
node tools/check-registry.mjs
echo "exit=$?"
```

Expected: `exit=0`.

- [ ] **Step 4: Commit**

```bash
git add tools/check-registry.mjs
git commit -m "feat(tools): check-registry.mjs — schema + sha256 audit"
```

---

## Phase D — CI

### Task 10: GitHub Actions lint workflow

**Files:**
- Create: `.github/workflows/lint.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: Lint

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Node.js 20
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"

      - name: Install dependencies
        run: npm ci

      - name: Lint every plugin file
        run: |
          set -euo pipefail
          shopt -s nullglob
          files=(plugins/*.js plugins/**/*.js)
          if [[ ${#files[@]} -eq 0 ]]; then
            echo "no plugin files found — nothing to lint"
            exit 0
          fi
          for f in "${files[@]}"; do
            echo "::group::$f"
            node tools/lint-plugin.mjs "$f"
            echo "::endgroup::"
          done

      - name: Validate registry.json (schema + sha256 audit)
        run: node tools/check-registry.mjs
```

- [ ] **Step 2: Commit and push to trigger the first workflow run**

```bash
git add .github/workflows/lint.yml
git commit -m "ci: lint workflow — runs lint-plugin + check-registry on push/PR"
git push origin main
```

- [ ] **Step 3: Watch the workflow result**

```bash
sleep 8
gh run list --limit 2
```

Expected: a row with `Lint`, `success`, on the latest commit.

If status is `in_progress`, poll again every 15s up to 2 minutes:

```bash
gh run watch $(gh run list --limit 1 --json databaseId --jq '.[0].databaseId')
```

Expected: workflow completes with exit code 0 across all steps.

---

## Phase E — Documentation

### Task 11: `docs/registry-schema.md`

**Files:**
- Create: `docs/registry-schema.md`

- [ ] **Step 1: Write the doc**

```markdown
# `registry.json` Schema and Verification Protocol

`registry.json` at the repo root is the single source of truth for which plugins exist, their version, and the sha256 of their file as committed. Clients fetch this file first; everything else flows from it.

## Schema

The full JSON Schema (draft-07) lives at `schemas/registry.schema.json`. Highlights:

- `format_version`: integer, must be `1`. Bumped only on a breaking change to the registry shape itself.
- `updated_at`: ISO-8601 UTC timestamp. Operator updates this on every push.
- `plugins`: array of plugin entries.

### Plugin entry fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `short_name` | string | yes | `^[a-z][a-z0-9_]{1,15}$`. Stable identifier the client uses to address the plugin. |
| `file` | string | yes | Path under `plugins/`. Must exist. |
| `version` | string | yes | Semver. Bumped per content change. |
| `api_version` | integer | yes | Currently `1`. Increment only when the host API contract changes. |
| `sha256` | string | yes | 64-char lowercase hex of the file contents. |
| `min_app_version` | string | no | If present, clients with `app_version < min_app_version` skip this plugin. |
| `capabilities` | string[] | yes | Subset of the closed enum (see `docs/plugin-contract.md`). |

## sha256 verification protocol

The client follows this protocol on every plugin update poll:

1. Fetch `registry.json` from the GitHub API using the per-user PAT.
2. For each entry whose `sha256` differs from the locally-installed copy:
   1. Fetch the `file` body from the GitHub API.
   2. Compute the sha256 of the downloaded body.
   3. Compare to `registry.json`'s `sha256`. **On mismatch: drop the file, log a warning, keep the previously-installed version active.**
   4. On match: validate the plugin against the contract (mirror of `tools/lint-plugin.mjs`), then mount in the QuickJS sandbox atomically (so an in-flight call to the previous version is not interrupted mid-execution).

The client never trusts a `.js` file whose sha256 doesn't match the registry. The registry is signed implicitly by GitHub's TLS + the PAT-authenticated read; integrity of registry → integrity of plugins.

## Worked examples

### Minimal — only the test fixture

```json
{
  "format_version": 1,
  "updated_at": "2026-05-10T00:00:00Z",
  "plugins": [
    {
      "short_name": "echo",
      "file": "plugins/_fixture/echo.js",
      "version": "1.0.0",
      "api_version": 1,
      "sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
      "capabilities": ["movie"]
    }
  ]
}
```

### One real plugin + the fixture

```json
{
  "format_version": 1,
  "updated_at": "2026-05-15T18:30:00Z",
  "plugins": [
    {
      "short_name": "sc",
      "file": "plugins/streamingcommunity.js",
      "version": "1.2.0",
      "api_version": 1,
      "sha256": "1111111111111111111111111111111111111111111111111111111111111111",
      "capabilities": ["movie", "tv", "tv:anime"]
    },
    {
      "short_name": "echo",
      "file": "plugins/_fixture/echo.js",
      "version": "1.0.0",
      "api_version": 1,
      "sha256": "2222222222222222222222222222222222222222222222222222222222222222",
      "capabilities": ["movie"]
    }
  ]
}
```

### A plugin gated on a future client version

```json
{
  "short_name": "raiplay",
  "file": "plugins/raiplay.js",
  "version": "2.0.0",
  "api_version": 1,
  "min_app_version": "0.4.0",
  "sha256": "3333333333333333333333333333333333333333333333333333333333333333",
  "capabilities": ["movie", "tv", "tv:news", "tv:documentary", "tv:kids"]
}
```

Clients running app_version `0.3.x` will silently skip this entry until they self-update.
```

- [ ] **Step 2: Commit**

```bash
git add docs/registry-schema.md
git commit -m "docs: registry schema + sha256 verification protocol"
```

---

### Task 12: `docs/plugin-contract.md`

**Files:**
- Create: `docs/plugin-contract.md`

- [ ] **Step 1: Write the doc**

```markdown
# Plugin Contract (api_version 1)

Every plugin is a single ESM `.js` file. It exports one `meta` object and four async functions. The Streamload client loads it inside a QuickJS sandbox via `flutter_js`. The plugin can call a fixed `host.*` API surface; nothing else is reachable.

## `meta` export

```ts
interface Meta {
  short_name: string;          // /^[a-z][a-z0-9_]{1,15}$/, stable identifier
  display_name: string;        // human-friendly, shown in the UI
  version: string;             // semver, bumped per content change
  api_version: 1;              // host contract version (only 1 today)
  capabilities: Capability[];  // see closed enum below
  min_app_version?: string;    // optional, "MAJOR.MINOR.PATCH"
}

type Capability =
  | "movie"
  | "movie:anime"
  | "movie:kids"
  | "movie:documentary"
  | "tv"
  | "tv:anime"
  | "tv:kids"
  | "tv:documentary"
  | "tv:reality"
  | "tv:news"
  | "tv:sport";
```

## Required functions

All four are async, all four must be exported.

```ts
interface MediaEntry {
  id: string;                  // service-internal id
  title: string;
  url: string;                 // full URL to the title's landing page
  type: "movie" | "tv";
  service: string;             // must equal meta.short_name
  year?: number | null;
  genre?: string | null;
  image_url?: string | null;
  description?: string | null;
}

interface Season {
  number: number;
  episode_count?: number;
  title?: string | null;
  id?: string | null;          // opaque, plugin-internal
}

interface Episode {
  number: number;
  season_number: number;
  title: string;
  url: string;
  id?: string | null;
  duration?: number | null;    // seconds
}

interface StreamBundle {
  manifest_url: string;        // HLS master URL
  headers?: Record<string, string>;  // forwarded by the local HLS proxy on every upstream request
  is_drm?: boolean;
  drm_keys?: Array<{ kid: string; key: string }> | null;
}

export async function search(query: string): Promise<MediaEntry[]>;
export async function getSeasons(entry: MediaEntry): Promise<Season[]>;
export async function getEpisodes(season: Season): Promise<Episode[]>;
export async function getStreams(target: MediaEntry | Episode): Promise<StreamBundle>;
```

For movies, `getSeasons` returns `[]` and `getEpisodes` is never called.

## Host API surface

Available globally as `host.*` inside the sandbox.

```ts
namespace host {
  namespace http {
    interface FetchInit {
      method?: "GET" | "POST" | "PUT" | "DELETE";
      headers?: Record<string, string>;
      body?: string;
      cookies?: Record<string, string>;
    }
    interface FetchResponse {
      status: number;
      headers: Record<string, string>;
      body: string;
      cookies: Record<string, string>;
      finalUrl: string;        // after redirects
    }
    function fetch(url: string, init?: FetchInit): Promise<FetchResponse>;
    // Defaults: 10s timeout, max 10MB body, max 5 redirects.
  }

  namespace html {
    interface Element {
      attr(name: string): string | null;
      text(): string;
      html(): string;
      find(selector: string): Element[];
    }
    interface Document {
      find(selector: string): Element[];
      querySelector(selector: string): Element | null;
    }
    function parse(text: string): Document;
  }

  namespace crypto {
    function aesDecrypt(buf: Uint8Array, key: Uint8Array, iv: Uint8Array): Uint8Array;
    function hmac(algorithm: "sha1" | "sha256", key: Uint8Array, data: Uint8Array): Uint8Array;
    function md5(data: Uint8Array | string): string;          // hex
    function sha256(data: Uint8Array | string): string;       // hex
    function base64(input: Uint8Array | string): string;
  }

  namespace log {
    function debug(message: string): void;
    function info(message: string): void;
    function warn(message: string): void;
    function error(message: string): void;
  }

  namespace storage {
    // Per-plugin namespace: keys are scoped to `plugin:{meta.short_name}:`.
    function get(key: string): Promise<string | null>;
    function set(key: string, value: string): Promise<void>;
    function delete(key: string): Promise<void>;
  }

  namespace url {
    function absolute(maybeRelative: string, base: string): string;
  }

  namespace json {
    function parse(text: string): unknown;
    function stringify(value: unknown, indent?: number): string;
  }
}
```

## Sandbox restrictions

The sandbox **does not** provide:

- `fs`, `process`, `require`, `import` of arbitrary modules — only the `host.*` API is reachable.
- `eval` and `Function(string)` — disabled by the QuickJS runtime configuration.
- Access to other plugins' `host.storage` namespace.
- Any reference to the application database, user session, or backend HTTP.
- Network access outside `host.http.fetch`.

## Versioning rules

| You changed… | Bump |
|---|---|
| Plugin internal logic, fixed a bug | `meta.version` patch (`1.0.0` → `1.0.1`) |
| Added a capability the plugin now serves | `meta.version` minor (`1.0.0` → `1.1.0`) |
| Plugin requires a host API not yet in the sandbox | `meta.api_version` (currently 1; will become 2 when host adds a new surface) |
| Plugin requires a client feature shipped after a specific app release | set `meta.min_app_version` |

`meta.version` is the user-visible version. `meta.api_version` is the contract version — clients refuse to load plugins whose `api_version` they do not understand.
```

- [ ] **Step 2: Commit**

```bash
git add docs/plugin-contract.md
git commit -m "docs: plugin contract (meta + 4 functions + host API)"
```

---

### Task 13: `docs/operator-runbook.md`

**Files:**
- Create: `docs/operator-runbook.md`

- [ ] **Step 1: Write the runbook**

```markdown
# Operator Runbook — adding or updating a plugin

These steps are what you (the operator) run on your laptop every time you change a plugin. CI enforces every step, so a mistake fails the workflow rather than reaching users.

## Prerequisites

- This repo cloned at `~/Desktop/Projects/streamload-plugins/`.
- Node.js 20+ available on PATH.
- `npm install` ran once after cloning.

## Add a new plugin

1. Create the file under `plugins/`:

   ```bash
   $EDITOR plugins/streamingcommunity.js
   ```

   Implement the four required functions per `docs/plugin-contract.md`.

2. Lint locally:

   ```bash
   node tools/lint-plugin.mjs plugins/streamingcommunity.js
   ```

   Fix any reported errors before continuing.

3. Compute its sha256:

   ```bash
   ./tools/sha256.sh plugins/streamingcommunity.js
   ```

4. Open `registry.json`, add the new plugin entry. Use the sha256 from step 3:

   ```json
   {
     "short_name": "sc",
     "file": "plugins/streamingcommunity.js",
     "version": "1.0.0",
     "api_version": 1,
     "sha256": "<paste sha256 here>",
     "capabilities": ["movie", "tv", "tv:anime"]
   }
   ```

   Bump `updated_at` to the current ISO-8601 UTC time:

   ```bash
   date -u +"%Y-%m-%dT%H:%M:%SZ"
   ```

5. Validate the whole registry:

   ```bash
   node tools/check-registry.mjs
   ```

   Expected: `✓ schema valid` and `✓ sc@1.0.0 — file + sha256 match`.

6. Commit + push:

   ```bash
   git add plugins/streamingcommunity.js registry.json
   git commit -m "feat(sc): initial StreamingCommunity plugin"
   git push origin main
   ```

7. CI will run the same lint + check-registry. Wait for green:

   ```bash
   gh run watch $(gh run list --limit 1 --json databaseId --jq '.[0].databaseId')
   ```

8. Within ~30 minutes, every running client picks up the change on its next registry poll. Force-pull is also possible from the Settings → Plugins screen.

## Update an existing plugin

Same flow, with one extra step: bump `meta.version` inside the plugin file AND inside `registry.json`. The `version` is what the client uses to detect "this plugin changed"; if you change the file but not the version, the client may serve a stale cached copy.

```bash
# 1. Edit the plugin
$EDITOR plugins/streamingcommunity.js

# 2. Bump meta.version inside the file (e.g. 1.0.0 → 1.0.1)

# 3. Re-hash
./tools/sha256.sh plugins/streamingcommunity.js

# 4. Edit registry.json — bump version + sha256 + updated_at

# 5. Lint + audit
node tools/lint-plugin.mjs plugins/streamingcommunity.js
node tools/check-registry.mjs

# 6. Commit + push
git add plugins/streamingcommunity.js registry.json
git commit -m "fix(sc): handle new search response shape (1.0.0 → 1.0.1)"
git push origin main
```

## Remove a plugin

1. Delete the file:

   ```bash
   git rm plugins/streamingcommunity.js
   ```

2. Remove its entry from `registry.json` (and bump `updated_at`).

3. `node tools/check-registry.mjs` to confirm.

4. Commit + push.

Clients pick up the removal on the next poll and unmount the plugin from the runtime.

## Common mistakes the linter catches

| Mistake | Linter message |
|---|---|
| Forgot to bump `sha256` after editing the file | `sha256 mismatch (registry=…, disk=…). Did you forget to run tools/sha256.sh after editing the file?` |
| Capability not in the closed enum | `meta.capabilities contains unknown value: "tv:music"` |
| Non-async function | `getSeasons must be declared async` |
| Bad `short_name` | `meta.short_name must match /^[a-z][a-z0-9_]{1,15}$/` |
| Bumped `api_version` past 1 | `meta.api_version must be 1` |

## Emergency: roll back a broken plugin

If a plugin update is broken in the wild:

1. `git revert <bad-commit>`.
2. The revert produces a new commit with the previous file + previous sha256 in registry.json.
3. Push. CI re-validates. Clients pick up the rollback within 30 min.

You do **not** need to delete the bad commit from history — clients only ever read the latest `main`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/operator-runbook.md
git commit -m "docs: operator runbook for add/update/remove/rollback"
```

---

### Task 14: `docs/end-user-pat.md`

**Files:**
- Create: `docs/end-user-pat.md`

- [ ] **Step 1: Write the doc**

```markdown
# End-user PAT — minting and distribution

Every Streamload-Client user needs a personal GitHub Personal Access Token to read this private repo. You (operator) generate one PAT per user, distribute it out-of-band, and the user pastes it once during onboarding.

The app stores the PAT in the OS keychain. It is never sent to the operator's server, never written to disk in plaintext, never logged.

## Preferred flow — fine-grained PAT (recommended)

Fine-grained tokens are scoped to a single repo and can be made read-only.

1. Sign in to GitHub as `alfanowski`.
2. Navigate: **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
3. Fill in:
   - **Token name**: `Streamload Plugin Pack — <username-of-recipient>`
   - **Expiration**: 1 year (or 90 days for stricter rotation; the user re-enters when expired).
   - **Repository access**: select **Only select repositories** → check **streamload-plugins**.
   - **Repository permissions**:
     - **Contents**: Read-only.
     - **Metadata**: Read-only (auto-selected, required for any read).
   - Leave everything else off.
4. Click **Generate token**. Copy the `github_pat_…` string immediately (GitHub shows it once).
5. Send to the user out-of-band:
   - **Preferred**: hand-deliver, or send via Signal in a disappearing message.
   - **Acceptable**: encrypted note in a password manager shared item (1Password, Bitwarden).
   - **Never**: email, SMS, plain Slack/Discord DM, GitHub-hosted gist.
6. Record in your operator log: who got which token, expiration date. (One line per user is enough.)

## Fallback — classic PAT (only if fine-grained is unavailable)

Classic PATs cannot be repo-scoped on private repos with read-only granularity, so they're broader than ideal. Use only as a fallback.

1. **Settings → Developer settings → Personal access tokens (classic) → Generate new token (classic)**.
2. **Note**: `Streamload Plugin Pack — <username>`.
3. **Expiration**: 1 year.
4. **Scopes**: check `repo` only. (`repo:read` does not exist as a separate scope on classic PATs; `repo` is the narrowest that grants read on a private repo.)
5. **Generate token**, copy, distribute the same way.

The classic PAT grants access to all of the operator's private repos. This is broader than the fine-grained alternative — only use it if the user's GitHub org policy disables fine-grained tokens.

## Rotation

When a token nears its expiration, mint a new one with the same name + new date and send to the user. The user re-enters in **Settings → Plugins → Update token** in the app. The old token can be revoked from the same GitHub UI page once the user confirms the new one works.

If a token is suspected leaked:

1. **Settings → Developer settings → Tokens → Revoke** the leaked token immediately.
2. Mint a replacement and deliver to the user.
3. Audit the repo's traffic via **Insights → Traffic** for unusual clones in the last 14 days.

## What the user sees

The app's first-run wizard step 3 shows:

```
"To access content, paste the GitHub Personal Access Token your administrator gave you."
[ _________________________________ ]
[ Verify and install ]
```

On verify, the app:

1. Calls `GET https://api.github.com/repos/alfanowski/streamload-plugins/contents/registry.json` with `Authorization: Bearer <pat>`.
2. On 200 → stores the PAT in the OS keychain (`flutter_secure_storage`), proceeds to download all plugins.
3. On 401/403 → shows "Invalid token. Ask your administrator for a new one." and stays on the wizard step.

The user never sees the underlying GitHub URL, doesn't need a GitHub account, doesn't need to know what a PAT is.
```

- [ ] **Step 2: Commit**

```bash
git add docs/end-user-pat.md
git commit -m "docs: per-user PAT minting + distribution + rotation"
```

---

### Task 15: `README.md` for the repo root

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

```markdown
# streamload-plugins (private)

Plugin pack for [Streamload v3](https://github.com/alfanowski/Streamload). Distributed out-of-band — this repo is private and the operator mints a per-user GitHub PAT for each end-user.

## Layout

```
streamload-plugins/
├── README.md                      ← you are here
├── registry.json                  ← machine-readable manifest (the client reads this first)
├── plugins/
│   ├── _fixture/echo.js           ← deterministic test fixture for client integration tests
│   └── *.js                       ← real scraping plugins (added per docs/operator-runbook.md)
├── docs/
│   ├── plugin-contract.md         ← TypeScript-style spec for plugin authors
│   ├── registry-schema.md         ← JSON Schema + sha256 verification protocol
│   ├── operator-runbook.md        ← "I want to add/update/remove a plugin"
│   └── end-user-pat.md            ← "How to mint a per-user PAT"
├── schemas/registry.schema.json   ← formal JSON Schema (used by check-registry.mjs)
├── tools/
│   ├── sha256.sh                  ← compute sha256 of a plugin file
│   ├── lint-plugin.mjs            ← per-file contract validator
│   └── check-registry.mjs         ← schema + sha256 audit
├── package.json                   ← tooling deps (ajv, ajv-formats)
└── .github/workflows/lint.yml     ← CI — runs both linters on every push
```

## I'm a plugin author — what do I do?

Read [`docs/plugin-contract.md`](docs/plugin-contract.md). It lists the four async functions you must export and the `host.*` API you can call.

Run the linter on your file before you push:

```bash
npm install
node tools/lint-plugin.mjs plugins/myplugin.js
```

## I'm the operator — what do I do?

Read [`docs/operator-runbook.md`](docs/operator-runbook.md). The TL;DR:

```bash
$EDITOR plugins/myplugin.js              # write or edit
./tools/sha256.sh plugins/myplugin.js    # get the new sha256
$EDITOR registry.json                    # update version + sha256 + updated_at
node tools/check-registry.mjs            # verify everything matches
git commit && git push
```

CI will re-run the linters on push and fail loudly if anything is off.

## I'm an end-user — what do I do?

Wait for the operator to send you a GitHub PAT (via Signal or in person). Paste it into the Streamload app's first-run wizard. That's it — the app polls this repo on its own from then on.

If your PAT stops working, ask the operator for a new one. Tokens expire; tokens get rotated.

## Legal / privacy

This repo contains scraping logic for Italian streaming services. It is **private**. The operator's identity is the GitHub account that owns it. Distribution is out-of-band only.

Do not fork, mirror, share commit URLs, or post screenshots. If you have a GitHub PAT to read this repo, you are an authorized end-user; that does not give you the right to redistribute the contents.
```

- [ ] **Step 2: Commit and push**

```bash
git add README.md
git commit -m "docs: README — repo overview + role-based getting-started"
git push origin main
```

- [ ] **Step 3: Watch CI go green on the README-only commit**

```bash
sleep 5
gh run list --limit 1
```

Expected: latest run, status `completed`, conclusion `success`.

---

## Phase F — Final smoke + acceptance

### Task 16: End-to-end dry run from a fresh clone

**Files:** none (validation only).

This task simulates what a brand-new operator clone looks like, ensuring nothing depends on local state.

- [ ] **Step 1: Clone into a temp directory**

```bash
TMPDIR=$(mktemp -d)
cd "$TMPDIR"
gh repo clone alfanowski/streamload-plugins
cd streamload-plugins
ls -la
```

Expected: 15 tracked files visible — README.md, registry.json, package.json, package-lock.json, .gitignore, schemas/registry.schema.json, plugins/_fixture/echo.js, docs/{plugin-contract,registry-schema,operator-runbook,end-user-pat}.md, tools/{sha256.sh,lint-plugin.mjs,check-registry.mjs}, .github/workflows/lint.yml. Run `git ls-files | wc -l` to verify; expect 15.

- [ ] **Step 2: Install + lint everything**

```bash
npm ci
node tools/lint-plugin.mjs plugins/_fixture/echo.js
node tools/check-registry.mjs
echo "all green"
```

Expected: each linter prints its `✓` lines and exits 0; final line `all green`.

- [ ] **Step 3: Cleanup**

```bash
cd /
rm -rf "$TMPDIR"
```

- [ ] **Step 4: Confirm CI is still green on origin/main**

```bash
gh run list --limit 1 --repo alfanowski/streamload-plugins
```

Expected: latest run `completed` / `success`.

---

### Task 17: Mint a smoke-test PAT and confirm the GitHub API path the client will use

**Files:** none (manual + curl validation).

The Flutter client (sub-plan #4) will hit `GET /repos/{owner}/{repo}/contents/registry.json`. Confirm the contract works end-to-end with a real PAT before any client code exists.

- [ ] **Step 1: Mint a fine-grained PAT scoped only to this repo**

Follow `docs/end-user-pat.md` "Preferred flow" and create a token named `Smoke test — streamload-plugins read-only`. Expiration: 7 days (this is a throwaway). Scopes: Contents = Read-only on `streamload-plugins` only. Copy the `github_pat_…` string to your clipboard.

- [ ] **Step 2: Curl the registry**

```bash
PAT="<paste-here>"
curl -s -H "Accept: application/vnd.github.v3+json" \
     -H "Authorization: Bearer $PAT" \
     https://api.github.com/repos/alfanowski/streamload-plugins/contents/registry.json | head -20
```

Expected: a JSON object with `name: "registry.json"`, `content: "<base64...>"`, `encoding: "base64"`.

Decode + verify it parses:

```bash
PAT="<paste-here>"
curl -s -H "Accept: application/vnd.github.v3+json" \
     -H "Authorization: Bearer $PAT" \
     https://api.github.com/repos/alfanowski/streamload-plugins/contents/registry.json \
  | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
content = base64.b64decode(d['content'])
parsed = json.loads(content)
print('format_version:', parsed['format_version'])
print('plugins:', [p['short_name'] for p in parsed['plugins']])
"
```

Expected:

```
format_version: 1
plugins: ['echo']
```

- [ ] **Step 3: Curl the fixture plugin and verify sha256 matches the registry**

```bash
PAT="<paste-here>"
ACTUAL=$(curl -s -H "Authorization: Bearer $PAT" \
              -H "Accept: application/vnd.github.v3.raw" \
              https://api.github.com/repos/alfanowski/streamload-plugins/contents/plugins/_fixture/echo.js \
         | shasum -a 256 | awk '{print $1}')
EXPECTED=$(curl -s -H "Authorization: Bearer $PAT" \
                -H "Accept: application/vnd.github.v3+json" \
                https://api.github.com/repos/alfanowski/streamload-plugins/contents/registry.json \
           | python3 -c "import sys, json, base64; d=json.load(sys.stdin); r=json.loads(base64.b64decode(d['content'])); print(r['plugins'][0]['sha256'])")
echo "actual:   $ACTUAL"
echo "expected: $EXPECTED"
test "$ACTUAL" = "$EXPECTED" && echo "MATCH" || echo "MISMATCH"
```

Expected: `MATCH`.

- [ ] **Step 4: Revoke the smoke-test PAT**

GitHub → Settings → Developer settings → Personal access tokens → Fine-grained → find `Smoke test — streamload-plugins read-only` → **Revoke**.

This PAT is throwaway and must not linger.

- [ ] **Step 5: Final state check**

```bash
cd /Users/alfanowski/Desktop/Projects/streamload-plugins
git log --oneline | wc -l
git status -sb
```

Expected: at least 14 commits (one per task above, plus possibly small fixups), branch `main` clean and in sync with `origin/main`.

---

## Plan complete

After Task 17 the operator has:

- A private GitHub repo `alfanowski/streamload-plugins` with all infrastructure in place.
- A green CI that catches every operator footgun (forgotten sha256 bump, broken plugin, schema-invalid registry, missing capabilities).
- A deterministic fixture plugin the Streamload-Client can integration-test against.
- Three docs that future-self (and any subagent) can follow without external context: contract, runbook, PAT distribution.
- A proven end-to-end path from "operator pushes a plugin" → "GitHub serves it" → "PAT-bearing client fetches + verifies it".

The client side of the loader (sandbox + sha256 verification + atomic mount) is sub-plan #4. Sub-plan #3 (Flutter foundation) and sub-plan #5 (HLS playback) do not depend on this repo at all and can proceed in parallel.
