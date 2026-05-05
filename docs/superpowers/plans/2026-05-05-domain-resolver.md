# Domain Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard-coded `domains = ["streamingcommunityz.nl"]` per-service list with a layered, signed, validated `DomainResolver` so domain rotation is handled centrally without releases.

**Architecture:** A `DomainResolver` queries a priority chain of sources (user config → local validated cache → signed remote manifest on GitHub raw → jsDelivr CDN mirror → hardcoded probe). Each candidate domain is actively validated against the live site (HTTP 200 + Inertia.js marker present) before being accepted. The remote manifest (`domains.json`) is Ed25519-signed; the public key is embedded in the package and the private key is held offline. A circuit breaker invalidates the cache on in-session failures and retries transparently.

**Tech Stack:** Python 3.11+, `cryptography` (Ed25519 — already a transitive dep, made explicit), existing `httpx` / `curl_cffi` HTTP client, `dataclasses`, `pytest` for tests (added by this plan), `fcntl` for cross-process locking.

---

## File Structure

**New module — `streamload/utils/domain_resolver/`:**
- `__init__.py` — public API: `DomainResolver`, exception types, `__all__`
- `models.py` — `DomainsManifest`, `ServiceDomains`, `ResolvedDomain` dataclasses
- `errors.py` — `DomainResolutionError`, `SignatureError`, `ManifestError`
- `signature.py` — Ed25519 verification using embedded trusted key
- `trusted_keys.py` — embedded public key constants
- `cache.py` — atomic JSON cache file with `fcntl` lock
- `validator.py` — active health check (HTTP + Inertia marker detection)
- `circuit_breaker.py` — in-session failure tracking, threshold-based invalidation
- `sources/__init__.py` — re-exports
- `sources/base.py` — `DomainSource` ABC
- `sources/config_source.py` — read override from `AppConfig.services.<short_name>.base_url`
- `sources/cache_source.py` — read from local cache file
- `sources/remote_source.py` — fetch signed manifest from GitHub raw, fallback to jsDelivr
- `sources/probe_source.py` — iterate the service's hardcoded `domains` list

**New tooling:**
- `tools/sign_domains.py` — CLI that signs `domains.json` using `secret/domains_signing_key.pem`

**New tests — `tests/utils/domain_resolver/`:**
- `conftest.py` — shared fixtures
- `test_signature.py`
- `test_cache.py`
- `test_validator.py`
- `test_circuit_breaker.py`
- `test_sources_config.py`
- `test_sources_cache.py`
- `test_sources_remote.py`
- `test_sources_probe.py`
- `test_resolver.py`
- `test_models.py`

**Modified files:**
- `requirements.txt` — add `cryptography>=42`, `pytest>=8` (dev), `pytest-mock>=3` (dev)
- `pyproject.toml` (created if missing) — pytest config
- `streamload/models/config.py` — add `ServicesConfig` and per-service override
- `streamload/services/base.py:154` — `base_url` becomes resolver-backed
- `streamload/services/streamingcommunity/__init__.py:53` — `domains` list becomes the *fallback probe seed*, not the only source
- `streamload/utils/config.py` — load/save `services` section
- `config.json.example` — document `services` override
- `streamload/cli/app.py` — register `domains` subcommand
- `streamload/utils/domain_resolver/trusted_keys.py` — embed the generated public key

**New manifest files at repo root (committed):**
- `domains.json` — service → domain mapping
- `domains.json.sig` — Ed25519 signature, base64

---

## Important conventions

- **Commit format:** Conventional Commits (`feat:`, `fix:`, `test:`, `refactor:`, `chore:`, `docs:`).
  **Do NOT add `Co-Authored-By` trailers** — user is sole author (per repo memory).
- **TDD:** every task is "test fails → implement → test passes → commit".
- **Keys:** `secret/domains_signing_key.pem` (private, gitignored), public b64 = `kCx2tMln4/ya6jmcdZo8l/Ew8eluVpw8DZ6aAgMGrDo=`, key_id = `sl-2026-05-53b1aa`.

---

## Task 0: Test infrastructure setup

**Files:**
- Create: `pyproject.toml`
- Modify: `requirements.txt`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/utils/__init__.py`
- Create: `tests/utils/domain_resolver/__init__.py`

- [ ] **Step 1: Add pytest + cryptography to requirements**

Append to `requirements.txt`:
```
cryptography>=42
pytest>=8
pytest-mock>=3
```

- [ ] **Step 2: Create `pyproject.toml` with pytest config**

```toml
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
addopts = "-q --strict-markers"
filterwarnings = ["error"]
```

- [ ] **Step 3: Create empty test package init files**

```bash
mkdir -p tests/utils/domain_resolver
: > tests/__init__.py
: > tests/utils/__init__.py
: > tests/utils/domain_resolver/__init__.py
```

- [ ] **Step 4: Create root `tests/conftest.py`**

```python
"""Pytest configuration and shared fixtures for Streamload tests."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `import streamload` from tests without installing the package.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```

- [ ] **Step 5: Install new deps and verify pytest discovers nothing yet**

Run:
```bash
venv/bin/pip install -r requirements.txt
venv/bin/pytest
```
Expected: `no tests ran` (exit 5 is OK; we have empty test dirs).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pyproject.toml tests/
git commit -m "chore: add pytest test infrastructure"
```

---

## Task 1: Embed trusted public key

**Files:**
- Create: `streamload/utils/domain_resolver/__init__.py`
- Create: `streamload/utils/domain_resolver/trusted_keys.py`
- Create: `tests/utils/domain_resolver/test_trusted_keys.py`

- [ ] **Step 1: Write failing test**

Create `tests/utils/domain_resolver/test_trusted_keys.py`:
```python
"""Verify the trusted Ed25519 public key constants are well-formed."""
from __future__ import annotations

import base64

from streamload.utils.domain_resolver.trusted_keys import TRUSTED_KEYS, current_key


def test_trusted_keys_dict_has_at_least_one_entry():
    assert len(TRUSTED_KEYS) >= 1


def test_each_trusted_key_is_32_bytes_ed25519():
    for key_id, b64 in TRUSTED_KEYS.items():
        raw = base64.b64decode(b64)
        assert len(raw) == 32, f"{key_id} is not 32 bytes"


def test_current_key_id_is_in_trusted_keys():
    key_id, b64 = current_key()
    assert key_id in TRUSTED_KEYS
    assert TRUSTED_KEYS[key_id] == b64


def test_current_key_id_matches_known_fingerprint():
    key_id, _ = current_key()
    assert key_id == "sl-2026-05-53b1aa"
```

- [ ] **Step 2: Run — fails with import error**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_trusted_keys.py -v`
Expected: FAIL — `ModuleNotFoundError: streamload.utils.domain_resolver`

- [ ] **Step 3: Create package init**

`streamload/utils/domain_resolver/__init__.py`:
```python
"""Domain resolver package — see DomainResolver in resolver module."""
from __future__ import annotations
```

- [ ] **Step 4: Create `trusted_keys.py`**

```python
"""Ed25519 public keys trusted to sign the domains manifest.

Keys are embedded at build time. To rotate, generate a new keypair, add
its public key here under a new key_id, and update CURRENT_KEY_ID. The
previous key_id stays for one release cycle so older clients still
verify manifests until they upgrade.
"""
from __future__ import annotations

# key_id -> base64-encoded raw 32-byte Ed25519 public key
TRUSTED_KEYS: dict[str, str] = {
    "sl-2026-05-53b1aa": "kCx2tMln4/ya6jmcdZo8l/Ew8eluVpw8DZ6aAgMGrDo=",
}

CURRENT_KEY_ID: str = "sl-2026-05-53b1aa"


def current_key() -> tuple[str, str]:
    """Return ``(key_id, public_key_b64)`` for the active signing key."""
    return CURRENT_KEY_ID, TRUSTED_KEYS[CURRENT_KEY_ID]
```

- [ ] **Step 5: Run — passes**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_trusted_keys.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add streamload/utils/domain_resolver/__init__.py streamload/utils/domain_resolver/trusted_keys.py tests/utils/domain_resolver/test_trusted_keys.py
git commit -m "feat(domain-resolver): embed Ed25519 trusted public key"
```

---

## Task 2: Manifest models

**Files:**
- Create: `streamload/utils/domain_resolver/models.py`
- Create: `streamload/utils/domain_resolver/errors.py`
- Create: `tests/utils/domain_resolver/test_models.py`

- [ ] **Step 1: Write failing tests**

`tests/utils/domain_resolver/test_models.py`:
```python
from __future__ import annotations

import pytest

from streamload.utils.domain_resolver.errors import ManifestError
from streamload.utils.domain_resolver.models import (
    DomainsManifest,
    ResolvedDomain,
    ServiceDomains,
)


def test_service_domains_all_candidates_orders_primary_first():
    sd = ServiceDomains(primary="a.tld", fallbacks=["b.tld", "c.tld"])
    assert sd.all_candidates() == ["a.tld", "b.tld", "c.tld"]


def test_service_domains_dedups_fallback_equal_to_primary():
    sd = ServiceDomains(primary="a.tld", fallbacks=["a.tld", "b.tld"])
    assert sd.all_candidates() == ["a.tld", "b.tld"]


def test_manifest_from_dict_parses_minimal_payload():
    payload = {
        "schema_version": 1,
        "key_id": "sl-2026-05-53b1aa",
        "issued_at": "2026-05-05T10:00:00Z",
        "ttl_seconds": 21600,
        "services": {
            "sc": {"primary": "x.tld", "fallbacks": []},
        },
    }
    m = DomainsManifest.from_dict(payload)
    assert m.schema_version == 1
    assert m.key_id == "sl-2026-05-53b1aa"
    assert m.ttl_seconds == 21600
    assert m.services["sc"].primary == "x.tld"


def test_manifest_from_dict_rejects_unknown_schema_version():
    payload = {
        "schema_version": 999,
        "key_id": "k",
        "issued_at": "2026-05-05T10:00:00Z",
        "ttl_seconds": 1,
        "services": {},
    }
    with pytest.raises(ManifestError, match="schema_version"):
        DomainsManifest.from_dict(payload)


def test_manifest_from_dict_rejects_missing_required_field():
    payload = {"schema_version": 1, "services": {}}
    with pytest.raises(ManifestError):
        DomainsManifest.from_dict(payload)


def test_manifest_get_domains_returns_none_for_unknown_service():
    m = DomainsManifest(
        schema_version=1,
        key_id="k",
        issued_at="2026-05-05T10:00:00Z",
        ttl_seconds=1,
        services={},
    )
    assert m.get_domains("sc") is None


def test_resolved_domain_carries_source_tag():
    rd = ResolvedDomain(domain="x.tld", source="cache", validated_at=123.0)
    assert rd.domain == "x.tld"
    assert rd.source == "cache"
```

- [ ] **Step 2: Run — fails with import errors**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_models.py -v`
Expected: FAIL.

- [ ] **Step 3: Create `errors.py`**

```python
"""Exception types for the domain resolver."""
from __future__ import annotations


class DomainResolutionError(Exception):
    """Raised when no source could produce a validated domain."""


class SignatureError(Exception):
    """Raised when the manifest signature is missing, malformed, or invalid."""


class ManifestError(Exception):
    """Raised when the manifest payload is structurally invalid."""
```

- [ ] **Step 4: Create `models.py`**

```python
"""Dataclasses for the domain manifest and resolution results."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import ManifestError

SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (1,)


@dataclass(frozen=True)
class ServiceDomains:
    """Per-service domain list: one primary plus ordered fallbacks."""

    primary: str
    fallbacks: list[str] = field(default_factory=list)

    def all_candidates(self) -> list[str]:
        """Return primary followed by fallbacks, deduped, order preserved."""
        seen: set[str] = set()
        out: list[str] = []
        for d in [self.primary, *self.fallbacks]:
            if d and d not in seen:
                seen.add(d)
                out.append(d)
        return out


@dataclass(frozen=True)
class DomainsManifest:
    """Versioned, signed manifest mapping service short_names to domains."""

    schema_version: int
    key_id: str
    issued_at: str
    ttl_seconds: int
    services: dict[str, ServiceDomains]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DomainsManifest":
        required = ("schema_version", "key_id", "issued_at", "ttl_seconds", "services")
        missing = [k for k in required if k not in payload]
        if missing:
            raise ManifestError(f"missing fields: {missing}")

        if payload["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
            raise ManifestError(
                f"unsupported schema_version {payload['schema_version']!r}; "
                f"supported: {SUPPORTED_SCHEMA_VERSIONS}"
            )

        services: dict[str, ServiceDomains] = {}
        raw_services = payload["services"]
        if not isinstance(raw_services, dict):
            raise ManifestError("'services' must be an object")
        for short_name, sd in raw_services.items():
            if not isinstance(sd, dict) or "primary" not in sd:
                raise ManifestError(f"service {short_name!r} missing 'primary'")
            services[short_name] = ServiceDomains(
                primary=str(sd["primary"]),
                fallbacks=[str(x) for x in sd.get("fallbacks", [])],
            )

        return cls(
            schema_version=int(payload["schema_version"]),
            key_id=str(payload["key_id"]),
            issued_at=str(payload["issued_at"]),
            ttl_seconds=int(payload["ttl_seconds"]),
            services=services,
        )

    def get_domains(self, short_name: str) -> ServiceDomains | None:
        return self.services.get(short_name)


@dataclass(frozen=True)
class ResolvedDomain:
    """A successfully resolved + validated domain, with provenance."""

    domain: str
    source: str  # "config" | "cache" | "remote-github" | "remote-jsdelivr" | "probe"
    validated_at: float  # unix epoch
```

- [ ] **Step 5: Run — passes**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_models.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add streamload/utils/domain_resolver/models.py streamload/utils/domain_resolver/errors.py tests/utils/domain_resolver/test_models.py
git commit -m "feat(domain-resolver): add manifest and resolution models"
```

---

## Task 3: Ed25519 signature verification

**Files:**
- Create: `streamload/utils/domain_resolver/signature.py`
- Create: `tests/utils/domain_resolver/test_signature.py`

- [ ] **Step 1: Write failing tests**

`tests/utils/domain_resolver/test_signature.py`:
```python
from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from streamload.utils.domain_resolver.errors import SignatureError
from streamload.utils.domain_resolver.signature import verify_manifest


def _gen_keypair() -> tuple[Ed25519PrivateKey, str]:
    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv, base64.b64encode(pub_raw).decode("ascii")


def test_verify_manifest_accepts_valid_signature():
    priv, pub_b64 = _gen_keypair()
    payload = b'{"schema_version":1}'
    sig = base64.b64encode(priv.sign(payload)).decode("ascii")
    trusted = {"k1": pub_b64}

    verify_manifest(payload, sig, key_id="k1", trusted_keys=trusted)


def test_verify_manifest_rejects_unknown_key_id():
    priv, pub_b64 = _gen_keypair()
    sig = base64.b64encode(priv.sign(b"x")).decode("ascii")
    with pytest.raises(SignatureError, match="unknown key_id"):
        verify_manifest(b"x", sig, key_id="nope", trusted_keys={"k1": pub_b64})


def test_verify_manifest_rejects_tampered_payload():
    priv, pub_b64 = _gen_keypair()
    sig = base64.b64encode(priv.sign(b"original")).decode("ascii")
    with pytest.raises(SignatureError, match="invalid"):
        verify_manifest(b"tampered", sig, key_id="k1", trusted_keys={"k1": pub_b64})


def test_verify_manifest_rejects_signature_from_different_key():
    _priv1, _pub1 = _gen_keypair()
    priv2, _pub2 = _gen_keypair()
    sig = base64.b64encode(priv2.sign(b"x")).decode("ascii")
    with pytest.raises(SignatureError, match="invalid"):
        verify_manifest(b"x", sig, key_id="k1", trusted_keys={"k1": _pub1})


def test_verify_manifest_rejects_malformed_b64_signature():
    _priv, pub_b64 = _gen_keypair()
    with pytest.raises(SignatureError, match="malformed"):
        verify_manifest(b"x", "not!base64!", key_id="k1", trusted_keys={"k1": pub_b64})
```

- [ ] **Step 2: Run — fails**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_signature.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `signature.py`**

```python
"""Ed25519 signature verification for the domains manifest."""
from __future__ import annotations

import base64
import binascii

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .errors import SignatureError


def verify_manifest(
    payload: bytes,
    signature_b64: str,
    *,
    key_id: str,
    trusted_keys: dict[str, str],
) -> None:
    """Verify *payload* was signed by the private key for *key_id*.

    Raises
    ------
    SignatureError
        If ``key_id`` is not trusted, the signature is malformed, or the
        cryptographic verification fails.
    """
    pub_b64 = trusted_keys.get(key_id)
    if pub_b64 is None:
        raise SignatureError(f"unknown key_id: {key_id!r}")

    try:
        pub_raw = base64.b64decode(pub_b64, validate=True)
        sig_raw = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError(f"malformed base64: {exc}") from exc

    if len(pub_raw) != 32:
        raise SignatureError(f"public key for {key_id!r} is not 32 bytes")

    try:
        Ed25519PublicKey.from_public_bytes(pub_raw).verify(sig_raw, payload)
    except InvalidSignature as exc:
        raise SignatureError("signature is invalid") from exc
```

- [ ] **Step 4: Run — passes**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_signature.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/utils/domain_resolver/signature.py tests/utils/domain_resolver/test_signature.py
git commit -m "feat(domain-resolver): Ed25519 manifest signature verification"
```

---

## Task 4: Atomic cache file with locking

**Files:**
- Create: `streamload/utils/domain_resolver/cache.py`
- Create: `tests/utils/domain_resolver/test_cache.py`

- [ ] **Step 1: Write failing tests**

`tests/utils/domain_resolver/test_cache.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from streamload.utils.domain_resolver.cache import DomainCache


@pytest.fixture
def cache(tmp_path: Path) -> DomainCache:
    return DomainCache(tmp_path / "domains_cache.json")


def test_get_returns_none_when_file_absent(cache: DomainCache):
    assert cache.get("sc") is None


def test_set_then_get_roundtrip(cache: DomainCache):
    cache.set("sc", domain="x.tld", source="remote-github", validated_at=100.0)
    entry = cache.get("sc")
    assert entry is not None
    assert entry["domain"] == "x.tld"
    assert entry["source"] == "remote-github"
    assert entry["validated_at"] == 100.0


def test_set_persists_atomically(cache: DomainCache, tmp_path: Path):
    cache.set("sc", domain="x.tld", source="cache", validated_at=1.0)
    raw = json.loads((tmp_path / "domains_cache.json").read_text())
    assert raw["entries"]["sc"]["domain"] == "x.tld"


def test_invalidate_removes_entry(cache: DomainCache):
    cache.set("sc", domain="x.tld", source="cache", validated_at=1.0)
    cache.invalidate("sc")
    assert cache.get("sc") is None


def test_invalidate_unknown_service_is_noop(cache: DomainCache):
    cache.invalidate("nope")  # must not raise


def test_corrupt_cache_file_is_treated_as_empty(cache: DomainCache, tmp_path: Path):
    (tmp_path / "domains_cache.json").write_text("{not json")
    assert cache.get("sc") is None


def test_is_fresh_uses_validated_at_and_ttl(cache: DomainCache):
    cache.set("sc", domain="x.tld", source="cache", validated_at=1000.0)
    assert cache.is_fresh("sc", ttl_seconds=10, now=1005.0) is True
    assert cache.is_fresh("sc", ttl_seconds=10, now=1011.0) is False
    assert cache.is_fresh("missing", ttl_seconds=10, now=1000.0) is False
```

- [ ] **Step 2: Run — fails**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_cache.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `cache.py`**

```python
"""Atomic, lock-protected JSON cache for resolved domains.

Schema:
    {
      "version": 1,
      "entries": {
        "<short_name>": {
          "domain": "x.tld",
          "source": "remote-github",
          "validated_at": 1714912345.0
        }
      }
    }
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    import fcntl  # type: ignore[import-not-found]
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover -- Windows
    _HAS_FCNTL = False


_SCHEMA_VERSION = 1


class DomainCache:
    """File-backed cache of resolved domains, safe across processes."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    # -- Read API ----------------------------------------------------------

    def get(self, short_name: str) -> dict[str, Any] | None:
        data = self._read()
        return data.get("entries", {}).get(short_name)

    def is_fresh(self, short_name: str, *, ttl_seconds: int, now: float | None = None) -> bool:
        entry = self.get(short_name)
        if entry is None:
            return False
        ts = float(entry.get("validated_at", 0))
        return ((now if now is not None else time.time()) - ts) < ttl_seconds

    # -- Write API ---------------------------------------------------------

    def set(self, short_name: str, *, domain: str, source: str, validated_at: float) -> None:
        def mutate(data: dict[str, Any]) -> dict[str, Any]:
            data.setdefault("entries", {})[short_name] = {
                "domain": domain,
                "source": source,
                "validated_at": validated_at,
            }
            return data

        self._mutate(mutate)

    def invalidate(self, short_name: str) -> None:
        def mutate(data: dict[str, Any]) -> dict[str, Any]:
            entries = data.get("entries", {})
            entries.pop(short_name, None)
            data["entries"] = entries
            return data

        self._mutate(mutate)

    # -- Internals ---------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": _SCHEMA_VERSION, "entries": {}}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"version": _SCHEMA_VERSION, "entries": {}}

    def _mutate(self, fn) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        with open(lock_path, "w") as lock_fh:
            if _HAS_FCNTL:
                fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                data = self._read()
                data = fn(data)
                self._atomic_write(data)
            finally:
                if _HAS_FCNTL:
                    fcntl.flock(lock_fh, fcntl.LOCK_UN)

    def _atomic_write(self, data: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(prefix=".cache-", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
```

- [ ] **Step 4: Run — passes**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_cache.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/utils/domain_resolver/cache.py tests/utils/domain_resolver/test_cache.py
git commit -m "feat(domain-resolver): atomic cache with cross-process lock"
```

---

## Task 5: Active validator (HTTP + Inertia marker)

**Files:**
- Create: `streamload/utils/domain_resolver/validator.py`
- Create: `tests/utils/domain_resolver/test_validator.py`

- [ ] **Step 1: Write failing tests**

`tests/utils/domain_resolver/test_validator.py`:
```python
from __future__ import annotations

from unittest.mock import MagicMock

from streamload.utils.domain_resolver.validator import validate_domain


def _resp(status: int, text: str):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


VALID_HTML = (
    '<html><body><div id="app" data-page=\''
    '{"version":"abc","props":{"foo":1}}\'></div></body></html>'
)


def test_validate_returns_true_on_valid_inertia_page():
    http = MagicMock()
    http.get.return_value = _resp(200, VALID_HTML)
    assert validate_domain(http, "x.tld") is True


def test_validate_rejects_non_200():
    http = MagicMock()
    http.get.return_value = _resp(404, VALID_HTML)
    assert validate_domain(http, "x.tld") is False


def test_validate_rejects_missing_app_div():
    http = MagicMock()
    http.get.return_value = _resp(200, "<html>parking page</html>")
    assert validate_domain(http, "x.tld") is False


def test_validate_rejects_app_div_without_data_page():
    http = MagicMock()
    http.get.return_value = _resp(200, '<div id="app"></div>')
    assert validate_domain(http, "x.tld") is False


def test_validate_rejects_data_page_missing_version():
    http = MagicMock()
    html = '<div id="app" data-page=\'{"props":{}}\'></div>'
    http.get.return_value = _resp(200, html)
    assert validate_domain(http, "x.tld") is False


def test_validate_rejects_data_page_missing_props():
    http = MagicMock()
    html = '<div id="app" data-page=\'{"version":"v"}\'></div>'
    http.get.return_value = _resp(200, html)
    assert validate_domain(http, "x.tld") is False


def test_validate_returns_false_on_http_exception():
    http = MagicMock()
    http.get.side_effect = RuntimeError("boom")
    assert validate_domain(http, "x.tld") is False


def test_validate_uses_curl_and_lang_path():
    http = MagicMock()
    http.get.return_value = _resp(200, VALID_HTML)
    validate_domain(http, "x.tld", lang="it")
    http.get.assert_called_once()
    args, kwargs = http.get.call_args
    assert args[0] == "https://x.tld/it"
    assert kwargs.get("use_curl") is True
```

- [ ] **Step 2: Run — fails**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_validator.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `validator.py`**

```python
"""Active health check that confirms a candidate domain serves the live site.

The check is service-shaped: it fetches ``/<lang>`` and verifies that the
response is an Inertia.js page with both ``version`` and ``props`` in the
``data-page`` JSON. This is enough to reject parking pages, ISP captive
portals, and squatted-but-online domains.

Currently only the StreamingCommunity shape is checked. When more services
are added, accept a ``shape`` parameter and dispatch.
"""
from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from streamload.utils.logger import get_logger

log = get_logger(__name__)

_VALIDATION_TIMEOUT_HINT = 10  # seconds; HttpClient honors its own config


def validate_domain(http: Any, domain: str, *, lang: str = "it") -> bool:
    """Return True if ``https://{domain}/{lang}`` serves a valid Inertia page."""
    url = f"https://{domain}/{lang}"
    try:
        resp = http.get(url, use_curl=True)
    except Exception:
        log.debug("validate_domain: GET failed for %s", url, exc_info=True)
        return False

    if getattr(resp, "status_code", 0) != 200:
        log.debug("validate_domain: status=%s for %s", resp.status_code, url)
        return False

    text = getattr(resp, "text", "") or ""
    soup = BeautifulSoup(text, "html.parser")
    app = soup.find("div", {"id": "app"})
    if app is None:
        return False

    data_page = app.get("data-page")
    if not data_page:
        return False

    try:
        page = json.loads(data_page)
    except (json.JSONDecodeError, TypeError):
        return False

    if not isinstance(page, dict):
        return False
    if "version" not in page or "props" not in page:
        return False

    return True
```

- [ ] **Step 4: Run — passes**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_validator.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/utils/domain_resolver/validator.py tests/utils/domain_resolver/test_validator.py
git commit -m "feat(domain-resolver): active Inertia.js health validator"
```

---

## Task 6: Circuit breaker

**Files:**
- Create: `streamload/utils/domain_resolver/circuit_breaker.py`
- Create: `tests/utils/domain_resolver/test_circuit_breaker.py`

- [ ] **Step 1: Write failing tests**

`tests/utils/domain_resolver/test_circuit_breaker.py`:
```python
from streamload.utils.domain_resolver.circuit_breaker import CircuitBreaker


def test_starts_closed():
    cb = CircuitBreaker(threshold=3)
    assert cb.is_open("sc") is False


def test_opens_after_threshold_failures():
    cb = CircuitBreaker(threshold=3)
    for _ in range(2):
        cb.record_failure("sc")
    assert cb.is_open("sc") is False
    cb.record_failure("sc")
    assert cb.is_open("sc") is True


def test_reset_clears_failures():
    cb = CircuitBreaker(threshold=2)
    cb.record_failure("sc")
    cb.record_failure("sc")
    assert cb.is_open("sc") is True
    cb.reset("sc")
    assert cb.is_open("sc") is False


def test_record_success_resets_failures():
    cb = CircuitBreaker(threshold=2)
    cb.record_failure("sc")
    cb.record_success("sc")
    cb.record_failure("sc")
    assert cb.is_open("sc") is False


def test_per_service_isolation():
    cb = CircuitBreaker(threshold=1)
    cb.record_failure("sc")
    assert cb.is_open("sc") is True
    assert cb.is_open("au") is False
```

- [ ] **Step 2: Run — fails**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_circuit_breaker.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `circuit_breaker.py`**

```python
"""In-memory per-service circuit breaker for domain failures.

Tracks consecutive failures since the last success. When the count crosses
*threshold* the breaker is open, signaling that the domain resolver should
invalidate its cache and re-resolve.

State is intentionally not persisted: a fresh process gets a clean slate,
so a brief outage doesn't keep a domain marked dead forever.
"""
from __future__ import annotations


class CircuitBreaker:
    def __init__(self, *, threshold: int = 3) -> None:
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        self._threshold = threshold
        self._failures: dict[str, int] = {}

    def record_failure(self, short_name: str) -> None:
        self._failures[short_name] = self._failures.get(short_name, 0) + 1

    def record_success(self, short_name: str) -> None:
        self._failures.pop(short_name, None)

    def reset(self, short_name: str) -> None:
        self._failures.pop(short_name, None)

    def is_open(self, short_name: str) -> bool:
        return self._failures.get(short_name, 0) >= self._threshold
```

- [ ] **Step 4: Run — passes**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_circuit_breaker.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/utils/domain_resolver/circuit_breaker.py tests/utils/domain_resolver/test_circuit_breaker.py
git commit -m "feat(domain-resolver): per-service circuit breaker"
```

---

## Task 7: Source ABC + ConfigSource

**Files:**
- Create: `streamload/utils/domain_resolver/sources/__init__.py`
- Create: `streamload/utils/domain_resolver/sources/base.py`
- Create: `streamload/utils/domain_resolver/sources/config_source.py`
- Create: `tests/utils/domain_resolver/test_sources_config.py`

- [ ] **Step 1: Write failing tests**

`tests/utils/domain_resolver/test_sources_config.py`:
```python
from streamload.utils.domain_resolver.sources.config_source import ConfigSource


def test_returns_none_when_no_override():
    src = ConfigSource(overrides={})
    assert src.candidates("sc") == []


def test_returns_override_when_present():
    src = ConfigSource(overrides={"sc": "my.tld"})
    assert src.candidates("sc") == ["my.tld"]


def test_strips_protocol_and_path_from_override():
    src = ConfigSource(overrides={"sc": "https://my.tld/it/"})
    assert src.candidates("sc") == ["my.tld"]


def test_ignores_blank_override():
    src = ConfigSource(overrides={"sc": "  "})
    assert src.candidates("sc") == []


def test_name():
    assert ConfigSource(overrides={}).name == "config"
```

- [ ] **Step 2: Run — fails**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_sources_config.py -v`
Expected: FAIL.

- [ ] **Step 3: Create source ABC**

`streamload/utils/domain_resolver/sources/__init__.py`:
```python
from .base import DomainSource
from .config_source import ConfigSource

__all__ = ["DomainSource", "ConfigSource"]
```

`streamload/utils/domain_resolver/sources/base.py`:
```python
"""Source ABC for the resolver chain.

Each source produces an ordered list of *candidate* domains for a service.
Candidates are then validated by the resolver before being accepted.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class DomainSource(ABC):
    """Produces ordered candidate domains for a service."""

    name: str

    @abstractmethod
    def candidates(self, short_name: str) -> list[str]:
        """Return the candidate domains, most-preferred first. Empty if none."""
        ...
```

- [ ] **Step 4: Implement `config_source.py`**

```python
"""Source that reads per-service overrides from the user config."""
from __future__ import annotations

from urllib.parse import urlparse

from .base import DomainSource


def _normalize(value: str) -> str:
    """Return bare hostname even if user wrote a full URL."""
    s = value.strip()
    if not s:
        return ""
    if "://" in s:
        parsed = urlparse(s)
        return parsed.netloc or ""
    return s.split("/", 1)[0]


class ConfigSource(DomainSource):
    """Reads overrides from ``AppConfig.services.<short_name>.base_url``."""

    name = "config"

    def __init__(self, *, overrides: dict[str, str]) -> None:
        self._overrides = overrides

    def candidates(self, short_name: str) -> list[str]:
        raw = self._overrides.get(short_name, "")
        host = _normalize(raw)
        return [host] if host else []
```

- [ ] **Step 5: Run — passes**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_sources_config.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add streamload/utils/domain_resolver/sources/ tests/utils/domain_resolver/test_sources_config.py
git commit -m "feat(domain-resolver): config-override source"
```

---

## Task 8: CacheSource

**Files:**
- Create: `streamload/utils/domain_resolver/sources/cache_source.py`
- Create: `tests/utils/domain_resolver/test_sources_cache.py`
- Modify: `streamload/utils/domain_resolver/sources/__init__.py`

- [ ] **Step 1: Write failing tests**

`tests/utils/domain_resolver/test_sources_cache.py`:
```python
from pathlib import Path

import pytest

from streamload.utils.domain_resolver.cache import DomainCache
from streamload.utils.domain_resolver.sources.cache_source import CacheSource


@pytest.fixture
def cache(tmp_path: Path) -> DomainCache:
    return DomainCache(tmp_path / "c.json")


def test_returns_empty_when_cache_missing(cache: DomainCache):
    src = CacheSource(cache=cache, ttl_seconds=60)
    assert src.candidates("sc") == []


def test_returns_cached_domain_when_fresh(cache: DomainCache):
    import time
    cache.set("sc", domain="x.tld", source="remote-github", validated_at=time.time())
    src = CacheSource(cache=cache, ttl_seconds=60)
    assert src.candidates("sc") == ["x.tld"]


def test_returns_empty_when_cache_stale(cache: DomainCache):
    cache.set("sc", domain="x.tld", source="cache", validated_at=0.0)
    src = CacheSource(cache=cache, ttl_seconds=10)
    assert src.candidates("sc") == []


def test_name(cache: DomainCache):
    assert CacheSource(cache=cache, ttl_seconds=1).name == "cache"
```

- [ ] **Step 2: Run — fails**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_sources_cache.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `cache_source.py`**

```python
"""Source that reads a previously validated domain from the local cache."""
from __future__ import annotations

from ..cache import DomainCache
from .base import DomainSource


class CacheSource(DomainSource):
    """Returns the cached domain when its validated_at is within TTL."""

    name = "cache"

    def __init__(self, *, cache: DomainCache, ttl_seconds: int) -> None:
        self._cache = cache
        self._ttl = ttl_seconds

    def candidates(self, short_name: str) -> list[str]:
        if not self._cache.is_fresh(short_name, ttl_seconds=self._ttl):
            return []
        entry = self._cache.get(short_name)
        if entry is None:
            return []
        domain = entry.get("domain")
        return [domain] if domain else []
```

- [ ] **Step 4: Update `sources/__init__.py` re-exports**

```python
from .base import DomainSource
from .cache_source import CacheSource
from .config_source import ConfigSource

__all__ = ["DomainSource", "CacheSource", "ConfigSource"]
```

- [ ] **Step 5: Run — passes**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_sources_cache.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add streamload/utils/domain_resolver/sources/cache_source.py streamload/utils/domain_resolver/sources/__init__.py tests/utils/domain_resolver/test_sources_cache.py
git commit -m "feat(domain-resolver): cache source for warm reboots"
```

---

## Task 9: RemoteSource (GitHub raw + jsDelivr)

**Files:**
- Create: `streamload/utils/domain_resolver/sources/remote_source.py`
- Create: `tests/utils/domain_resolver/test_sources_remote.py`
- Modify: `streamload/utils/domain_resolver/sources/__init__.py`

- [ ] **Step 1: Write failing tests**

`tests/utils/domain_resolver/test_sources_remote.py`:
```python
from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from streamload.utils.domain_resolver.sources.remote_source import RemoteSource


def _sign(payload: bytes, priv: Ed25519PrivateKey) -> str:
    return base64.b64encode(priv.sign(payload)).decode("ascii")


def _pub_b64(priv: Ed25519PrivateKey) -> str:
    raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def _resp(status: int, text: str):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


@pytest.fixture
def signed_manifest():
    priv = Ed25519PrivateKey.generate()
    payload = {
        "schema_version": 1,
        "key_id": "k1",
        "issued_at": "2026-05-05T10:00:00Z",
        "ttl_seconds": 60,
        "services": {"sc": {"primary": "x.tld", "fallbacks": ["y.tld"]}},
    }
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    sig = _sign(body, priv)
    return body.decode("utf-8"), sig, {"k1": _pub_b64(priv)}


def test_returns_primary_then_fallbacks_on_github_success(signed_manifest):
    body, sig, trusted = signed_manifest
    http = MagicMock()
    http.get.side_effect = [_resp(200, body), _resp(200, sig)]

    src = RemoteSource(
        http=http,
        repo="alfanowski/Streamload",
        branch="main",
        manifest_filename="domains.json",
        trusted_keys=trusted,
    )
    assert src.candidates("sc") == ["x.tld", "y.tld"]


def test_falls_back_to_jsdelivr_when_github_5xx(signed_manifest):
    body, sig, trusted = signed_manifest
    http = MagicMock()
    http.get.side_effect = [
        _resp(503, ""),  # github body
        _resp(200, body),  # jsdelivr body
        _resp(200, sig),  # jsdelivr sig
    ]
    src = RemoteSource(
        http=http,
        repo="alfanowski/Streamload",
        branch="main",
        manifest_filename="domains.json",
        trusted_keys=trusted,
    )
    assert src.candidates("sc") == ["x.tld", "y.tld"]


def test_returns_empty_when_signature_invalid(signed_manifest):
    body, _good_sig, trusted = signed_manifest
    bad_sig = base64.b64encode(b"\x00" * 64).decode("ascii")
    http = MagicMock()
    http.get.side_effect = [_resp(200, body), _resp(200, bad_sig)]

    src = RemoteSource(
        http=http,
        repo="r/r",
        branch="main",
        manifest_filename="domains.json",
        trusted_keys=trusted,
    )
    assert src.candidates("sc") == []


def test_returns_empty_when_service_unknown_in_manifest(signed_manifest):
    body, sig, trusted = signed_manifest
    http = MagicMock()
    http.get.side_effect = [_resp(200, body), _resp(200, sig)]

    src = RemoteSource(
        http=http,
        repo="r/r",
        branch="main",
        manifest_filename="domains.json",
        trusted_keys=trusted,
    )
    assert src.candidates("au") == []


def test_caches_manifest_within_instance_to_avoid_double_fetch(signed_manifest):
    body, sig, trusted = signed_manifest
    http = MagicMock()
    http.get.side_effect = [_resp(200, body), _resp(200, sig)]
    src = RemoteSource(
        http=http,
        repo="r/r",
        branch="main",
        manifest_filename="domains.json",
        trusted_keys=trusted,
    )
    src.candidates("sc")
    src.candidates("sc")
    assert http.get.call_count == 2  # only one body fetch + one sig fetch total


def test_name():
    src = RemoteSource(http=MagicMock(), repo="r/r", branch="main",
                       manifest_filename="domains.json", trusted_keys={})
    assert src.name == "remote"
```

- [ ] **Step 2: Run — fails**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_sources_remote.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `remote_source.py`**

```python
"""Source that fetches the signed manifest from GitHub raw, with jsDelivr fallback.

Two independent routes to the same upstream content:

    primary  -> https://raw.githubusercontent.com/{repo}/{branch}/{file}
    fallback -> https://cdn.jsdelivr.net/gh/{repo}@{branch}/{file}

The signature file lives next to the manifest as ``<file>.sig``.
"""
from __future__ import annotations

import json
from typing import Any

from streamload.utils.logger import get_logger

from ..errors import ManifestError, SignatureError
from ..models import DomainsManifest
from ..signature import verify_manifest
from .base import DomainSource

log = get_logger(__name__)


class RemoteSource(DomainSource):
    name = "remote"

    def __init__(
        self,
        *,
        http: Any,
        repo: str,
        branch: str,
        manifest_filename: str,
        trusted_keys: dict[str, str],
    ) -> None:
        self._http = http
        self._repo = repo
        self._branch = branch
        self._file = manifest_filename
        self._trusted = trusted_keys
        self._cached: DomainsManifest | None = None
        self._tried = False

    def candidates(self, short_name: str) -> list[str]:
        manifest = self._load()
        if manifest is None:
            return []
        sd = manifest.get_domains(short_name)
        if sd is None:
            return []
        return sd.all_candidates()

    # -- internals --------------------------------------------------------

    def _load(self) -> DomainsManifest | None:
        if self._tried:
            return self._cached
        self._tried = True

        for route, url_body, url_sig in self._routes():
            body = self._fetch(url_body)
            if body is None:
                continue
            sig = self._fetch(url_sig)
            if sig is None:
                continue
            try:
                payload = json.loads(body)
                key_id = payload.get("key_id")
                if not isinstance(key_id, str):
                    raise ManifestError("missing key_id")
                verify_manifest(
                    body.encode("utf-8"),
                    sig.strip(),
                    key_id=key_id,
                    trusted_keys=self._trusted,
                )
                self._cached = DomainsManifest.from_dict(payload)
                log.info("Loaded domains manifest via %s (key_id=%s)", route, key_id)
                return self._cached
            except (json.JSONDecodeError, ManifestError, SignatureError) as exc:
                log.warning("Manifest from %s rejected: %s", route, exc)
                continue
        return None

    def _routes(self) -> list[tuple[str, str, str]]:
        gh_body = f"https://raw.githubusercontent.com/{self._repo}/{self._branch}/{self._file}"
        gh_sig = f"{gh_body}.sig"
        jd_body = f"https://cdn.jsdelivr.net/gh/{self._repo}@{self._branch}/{self._file}"
        jd_sig = f"{jd_body}.sig"
        return [("github", gh_body, gh_sig), ("jsdelivr", jd_body, jd_sig)]

    def _fetch(self, url: str) -> str | None:
        try:
            r = self._http.get(url)
            if getattr(r, "status_code", 0) != 200:
                return None
            return getattr(r, "text", None)
        except Exception:
            log.debug("Remote fetch failed for %s", url, exc_info=True)
            return None
```

- [ ] **Step 4: Update `sources/__init__.py`**

```python
from .base import DomainSource
from .cache_source import CacheSource
from .config_source import ConfigSource
from .remote_source import RemoteSource

__all__ = ["DomainSource", "CacheSource", "ConfigSource", "RemoteSource"]
```

- [ ] **Step 5: Run — passes**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_sources_remote.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add streamload/utils/domain_resolver/sources/remote_source.py streamload/utils/domain_resolver/sources/__init__.py tests/utils/domain_resolver/test_sources_remote.py
git commit -m "feat(domain-resolver): signed remote manifest source with jsDelivr fallback"
```

---

## Task 10: ProbeSource

**Files:**
- Create: `streamload/utils/domain_resolver/sources/probe_source.py`
- Create: `tests/utils/domain_resolver/test_sources_probe.py`
- Modify: `streamload/utils/domain_resolver/sources/__init__.py`

- [ ] **Step 1: Write failing tests**

`tests/utils/domain_resolver/test_sources_probe.py`:
```python
from streamload.utils.domain_resolver.sources.probe_source import ProbeSource


def test_returns_seed_list_for_known_service():
    src = ProbeSource(seeds={"sc": ["a.tld", "b.tld"]})
    assert src.candidates("sc") == ["a.tld", "b.tld"]


def test_returns_empty_for_unknown_service():
    src = ProbeSource(seeds={})
    assert src.candidates("sc") == []


def test_name():
    assert ProbeSource(seeds={}).name == "probe"
```

- [ ] **Step 2: Run — fails**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_sources_probe.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `probe_source.py`**

```python
"""Last-resort source: hardcoded historical domains from the service class."""
from __future__ import annotations

from .base import DomainSource


class ProbeSource(DomainSource):
    """Returns the service's hardcoded fallback list (last-known-good seed)."""

    name = "probe"

    def __init__(self, *, seeds: dict[str, list[str]]) -> None:
        self._seeds = seeds

    def candidates(self, short_name: str) -> list[str]:
        return list(self._seeds.get(short_name, []))
```

- [ ] **Step 4: Update `sources/__init__.py`**

```python
from .base import DomainSource
from .cache_source import CacheSource
from .config_source import ConfigSource
from .probe_source import ProbeSource
from .remote_source import RemoteSource

__all__ = [
    "DomainSource",
    "CacheSource",
    "ConfigSource",
    "ProbeSource",
    "RemoteSource",
]
```

- [ ] **Step 5: Run — passes**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_sources_probe.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add streamload/utils/domain_resolver/sources/probe_source.py streamload/utils/domain_resolver/sources/__init__.py tests/utils/domain_resolver/test_sources_probe.py
git commit -m "feat(domain-resolver): hardcoded-seed probe source"
```

---

## Task 11: DomainResolver orchestration

**Files:**
- Create: `streamload/utils/domain_resolver/resolver.py`
- Modify: `streamload/utils/domain_resolver/__init__.py`
- Create: `tests/utils/domain_resolver/test_resolver.py`

- [ ] **Step 1: Write failing tests**

`tests/utils/domain_resolver/test_resolver.py`:
```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from streamload.utils.domain_resolver.cache import DomainCache
from streamload.utils.domain_resolver.circuit_breaker import CircuitBreaker
from streamload.utils.domain_resolver.errors import DomainResolutionError
from streamload.utils.domain_resolver.resolver import DomainResolver
from streamload.utils.domain_resolver.sources.base import DomainSource


class _StaticSource(DomainSource):
    def __init__(self, name: str, mapping: dict[str, list[str]]):
        self.name = name
        self._m = mapping
    def candidates(self, short_name: str) -> list[str]:
        return list(self._m.get(short_name, []))


@pytest.fixture
def cache(tmp_path: Path) -> DomainCache:
    return DomainCache(tmp_path / "c.json")


def _validator(allowed: set[str]):
    def fn(http, domain, lang="it"):
        return domain in allowed
    return fn


def test_returns_first_validated_candidate(cache: DomainCache):
    sources = [
        _StaticSource("config", {"sc": ["bad1.tld"]}),
        _StaticSource("remote", {"sc": ["bad2.tld", "good.tld", "also-good.tld"]}),
    ]
    r = DomainResolver(
        sources=sources,
        cache=cache,
        validator=_validator({"good.tld", "also-good.tld"}),
        http=MagicMock(),
        breaker=CircuitBreaker(threshold=3),
    )
    resolved = r.resolve("sc")
    assert resolved.domain == "good.tld"
    assert resolved.source == "remote"


def test_writes_to_cache_on_success(cache: DomainCache):
    sources = [_StaticSource("remote", {"sc": ["x.tld"]})]
    r = DomainResolver(
        sources=sources,
        cache=cache,
        validator=_validator({"x.tld"}),
        http=MagicMock(),
        breaker=CircuitBreaker(threshold=3),
    )
    r.resolve("sc")
    entry = cache.get("sc")
    assert entry is not None
    assert entry["domain"] == "x.tld"


def test_skips_remaining_sources_after_first_validated_hit(cache: DomainCache):
    s1 = _StaticSource("config", {"sc": ["x.tld"]})
    s2 = MagicMock()
    s2.name = "remote"
    s2.candidates.return_value = []
    r = DomainResolver(
        sources=[s1, s2],
        cache=cache,
        validator=_validator({"x.tld"}),
        http=MagicMock(),
        breaker=CircuitBreaker(threshold=3),
    )
    r.resolve("sc")
    s2.candidates.assert_not_called()


def test_raises_when_no_source_yields_validated_domain(cache: DomainCache):
    sources = [_StaticSource("probe", {"sc": ["nope.tld"]})]
    r = DomainResolver(
        sources=sources,
        cache=cache,
        validator=_validator(set()),
        http=MagicMock(),
        breaker=CircuitBreaker(threshold=3),
    )
    with pytest.raises(DomainResolutionError):
        r.resolve("sc")


def test_invalidate_clears_cache_and_resets_breaker(cache: DomainCache):
    cache.set("sc", domain="x.tld", source="cache", validated_at=1.0)
    breaker = CircuitBreaker(threshold=2)
    breaker.record_failure("sc")
    r = DomainResolver(
        sources=[],
        cache=cache,
        validator=_validator(set()),
        http=MagicMock(),
        breaker=breaker,
    )
    r.invalidate("sc")
    assert cache.get("sc") is None


def test_record_failure_invalidates_when_breaker_opens(cache: DomainCache):
    cache.set("sc", domain="x.tld", source="cache", validated_at=1.0)
    breaker = CircuitBreaker(threshold=2)
    r = DomainResolver(
        sources=[],
        cache=cache,
        validator=_validator(set()),
        http=MagicMock(),
        breaker=breaker,
    )
    r.record_failure("sc")
    assert cache.get("sc") is not None  # not yet
    r.record_failure("sc")
    assert cache.get("sc") is None  # breaker opened -> invalidated
```

- [ ] **Step 2: Run — fails**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_resolver.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `resolver.py`**

```python
"""DomainResolver — orchestrates the source chain, validator and cache.

Public flow:

    resolve(short_name) -> ResolvedDomain
        for each source in priority order:
            for each candidate from that source:
                if validator(candidate) is True:
                    cache.set(...)
                    breaker.reset(short_name)
                    return ResolvedDomain(...)
        raise DomainResolutionError

Failures observed at runtime by callers (downstream HTTP errors) feed back
in via record_failure(); when the breaker opens, the cache is invalidated
so the next resolve() walks the chain afresh.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from streamload.utils.logger import get_logger

from .cache import DomainCache
from .circuit_breaker import CircuitBreaker
from .errors import DomainResolutionError
from .models import ResolvedDomain
from .sources.base import DomainSource

log = get_logger(__name__)

Validator = Callable[[Any, str], bool]  # (http, domain) -> ok
ValidatorWithLang = Callable[[Any, str, str], bool]


class DomainResolver:
    def __init__(
        self,
        *,
        sources: Sequence[DomainSource],
        cache: DomainCache,
        validator: Callable[..., bool],
        http: Any,
        breaker: CircuitBreaker,
        lang: str = "it",
    ) -> None:
        self._sources = list(sources)
        self._cache = cache
        self._validate = validator
        self._http = http
        self._breaker = breaker
        self._lang = lang

    def resolve(self, short_name: str) -> ResolvedDomain:
        for source in self._sources:
            try:
                candidates = source.candidates(short_name)
            except Exception:
                log.warning("Source %s raised; skipping", source.name, exc_info=True)
                continue

            for domain in candidates:
                if self._validate(self._http, domain, self._lang):
                    now = time.time()
                    self._cache.set(
                        short_name,
                        domain=domain,
                        source=source.name,
                        validated_at=now,
                    )
                    self._breaker.reset(short_name)
                    log.info(
                        "Resolved %s -> %s via %s",
                        short_name, domain, source.name,
                    )
                    return ResolvedDomain(
                        domain=domain,
                        source=source.name,
                        validated_at=now,
                    )
                log.debug("Candidate %s from %s did not validate", domain, source.name)

        raise DomainResolutionError(
            f"no source produced a validated domain for service {short_name!r}"
        )

    def record_failure(self, short_name: str) -> None:
        self._breaker.record_failure(short_name)
        if self._breaker.is_open(short_name):
            log.warning(
                "Circuit breaker opened for %s; invalidating cache", short_name,
            )
            self.invalidate(short_name)

    def record_success(self, short_name: str) -> None:
        self._breaker.record_success(short_name)

    def invalidate(self, short_name: str) -> None:
        self._cache.invalidate(short_name)
        self._breaker.reset(short_name)
```

- [ ] **Step 4: Update package init**

`streamload/utils/domain_resolver/__init__.py`:
```python
"""Domain resolver public API."""
from __future__ import annotations

from .errors import DomainResolutionError, ManifestError, SignatureError
from .models import DomainsManifest, ResolvedDomain, ServiceDomains
from .resolver import DomainResolver

__all__ = [
    "DomainResolver",
    "DomainResolutionError",
    "ManifestError",
    "SignatureError",
    "DomainsManifest",
    "ResolvedDomain",
    "ServiceDomains",
]
```

- [ ] **Step 5: Run — passes**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_resolver.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add streamload/utils/domain_resolver/resolver.py streamload/utils/domain_resolver/__init__.py tests/utils/domain_resolver/test_resolver.py
git commit -m "feat(domain-resolver): orchestrating DomainResolver with circuit breaker"
```

---

## Task 12: Extend AppConfig with services overrides

**Files:**
- Modify: `streamload/models/config.py`
- Modify: `config.json.example`
- Create: `tests/test_config_services.py`

- [ ] **Step 1: Write failing test**

`tests/test_config_services.py`:
```python
from streamload.models.config import AppConfig


def test_services_section_defaults_to_empty_dict():
    cfg = AppConfig.from_dict({})
    assert cfg.services == {}


def test_services_section_parses_overrides():
    cfg = AppConfig.from_dict({
        "services": {"sc": {"base_url": "https://my.tld"}},
    })
    assert cfg.services == {"sc": {"base_url": "https://my.tld"}}


def test_services_section_ignores_non_dict():
    cfg = AppConfig.from_dict({"services": "garbage"})
    assert cfg.services == {}
```

- [ ] **Step 2: Run — fails**

Run: `venv/bin/pytest tests/test_config_services.py -v`
Expected: FAIL — `services` attribute missing.

- [ ] **Step 3: Modify `streamload/models/config.py`**

Read the current `AppConfig` (around line 267) and:

a) Add field `services: dict[str, dict[str, str]] = field(default_factory=dict)` to the `AppConfig` dataclass.

b) In `AppConfig.from_dict`, after the existing field parsing, add:

```python
raw_services = data.get("services", {})
if not isinstance(raw_services, dict):
    raw_services = {}
clean_services: dict[str, dict[str, str]] = {}
for short_name, sec in raw_services.items():
    if isinstance(sec, dict):
        clean_services[short_name] = {
            k: str(v) for k, v in sec.items() if isinstance(v, (str, int, float))
        }
```

Then pass `services=clean_services` to the constructor.

If the file uses `asdict` for serialization, no changes are needed for write-back — `services` is already a plain dict.

- [ ] **Step 4: Add example to `config.json.example`**

Add inside the top-level object, before the closing brace:

```json
    "services": {
        "sc": {
            "base_url": ""
        }
    }
```

(Empty string = use resolver. Set to a hostname like `"streamingcommunityz.nl"` to force.)

- [ ] **Step 5: Run — passes**

Run: `venv/bin/pytest tests/test_config_services.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add streamload/models/config.py config.json.example tests/test_config_services.py
git commit -m "feat(config): add per-service overrides section"
```

---

## Task 13: Wire resolver into ServiceBase.base_url

**Files:**
- Modify: `streamload/services/base.py`
- Modify: `streamload/services/streamingcommunity/__init__.py`
- Create: `streamload/utils/domain_resolver/factory.py`
- Create: `tests/test_service_base_resolver.py`
- Create: `tests/utils/domain_resolver/test_factory.py`

- [ ] **Step 1: Write failing factory test**

`tests/utils/domain_resolver/test_factory.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock

from streamload.utils.domain_resolver.factory import build_resolver


def test_build_resolver_returns_configured_instance(tmp_path: Path):
    http = MagicMock()
    cfg_overrides = {"sc": "x.tld"}
    seeds = {"sc": ["seed.tld"]}
    resolver = build_resolver(
        http=http,
        config_overrides=cfg_overrides,
        probe_seeds=seeds,
        cache_path=tmp_path / "c.json",
        repo="alfanowski/Streamload",
        branch="main",
    )
    assert resolver is not None
```

- [ ] **Step 2: Run — fails**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_factory.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `factory.py`**

```python
"""Factory that wires the standard source chain for production use."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .cache import DomainCache
from .circuit_breaker import CircuitBreaker
from .resolver import DomainResolver
from .sources import CacheSource, ConfigSource, ProbeSource, RemoteSource
from .trusted_keys import TRUSTED_KEYS
from .validator import validate_domain

DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6h
MANIFEST_FILENAME = "domains.json"


def build_resolver(
    *,
    http: Any,
    config_overrides: dict[str, str],
    probe_seeds: dict[str, list[str]],
    cache_path: Path,
    repo: str,
    branch: str = "main",
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    breaker_threshold: int = 3,
    lang: str = "it",
) -> DomainResolver:
    cache = DomainCache(cache_path)
    sources = [
        ConfigSource(overrides=config_overrides),
        CacheSource(cache=cache, ttl_seconds=cache_ttl_seconds),
        RemoteSource(
            http=http,
            repo=repo,
            branch=branch,
            manifest_filename=MANIFEST_FILENAME,
            trusted_keys=TRUSTED_KEYS,
        ),
        ProbeSource(seeds=probe_seeds),
    ]
    return DomainResolver(
        sources=sources,
        cache=cache,
        validator=validate_domain,
        http=http,
        breaker=CircuitBreaker(threshold=breaker_threshold),
        lang=lang,
    )
```

- [ ] **Step 4: Run — passes**

Run: `venv/bin/pytest tests/utils/domain_resolver/test_factory.py -v`
Expected: 1 passed.

- [ ] **Step 5: Write failing ServiceBase test**

`tests/test_service_base_resolver.py`:
```python
from __future__ import annotations

from unittest.mock import MagicMock

from streamload.models.media import ServiceCategory
from streamload.services.base import ServiceBase


class _Dummy(ServiceBase):
    name = "Dummy"
    short_name = "dummy"
    domains = ["seed.tld"]
    category = ServiceCategory.FILM_SERIE
    language = "it"

    def search(self, q): return []
    def get_seasons(self, e): return []
    def get_episodes(self, s): return []
    def get_streams(self, i): raise NotImplementedError


def test_base_url_falls_back_to_first_domain_when_no_resolver():
    s = _Dummy(http_client=MagicMock())
    assert s.base_url == "https://seed.tld"


def test_base_url_uses_resolver_when_attached():
    s = _Dummy(http_client=MagicMock())
    resolver = MagicMock()
    resolver.resolve.return_value = MagicMock(domain="resolved.tld")
    s.attach_resolver(resolver)
    assert s.base_url == "https://resolved.tld"
    resolver.resolve.assert_called_once_with("dummy")


def test_base_url_caches_resolved_domain_per_instance():
    s = _Dummy(http_client=MagicMock())
    resolver = MagicMock()
    resolver.resolve.return_value = MagicMock(domain="resolved.tld")
    s.attach_resolver(resolver)
    _ = s.base_url
    _ = s.base_url
    resolver.resolve.assert_called_once()
```

- [ ] **Step 6: Run — fails**

Run: `venv/bin/pytest tests/test_service_base_resolver.py -v`
Expected: FAIL.

- [ ] **Step 7: Modify `streamload/services/base.py`**

Replace the `base_url` property (currently at line 154) and add resolver attach methods. Add near other helpers:

```python
def attach_resolver(self, resolver: Any) -> None:
    """Wire a DomainResolver. Subsequent base_url reads route through it."""
    self._resolver = resolver
    self._resolved_domain: str | None = None

@property
def base_url(self) -> str:
    """Return ``https://<resolved>`` via DomainResolver when attached.

    Falls back to ``https://{domains[0]}`` when no resolver is attached
    (used by tests / standalone scripts).
    """
    resolver = getattr(self, "_resolver", None)
    if resolver is not None:
        if getattr(self, "_resolved_domain", None) is None:
            self._resolved_domain = resolver.resolve(self.short_name).domain
        return f"https://{self._resolved_domain}"
    return f"https://{self.domains[0]}" if self.domains else ""
```

Also add `_resolver` and `_resolved_domain` initialization in `__init__`:

```python
def __init__(self, http_client: HttpClient) -> None:
    self._http: HttpClient = http_client
    self._session: AuthSession | None = None
    self._resolver = None
    self._resolved_domain: str | None = None
```

- [ ] **Step 8: Run — passes**

Run: `venv/bin/pytest tests/test_service_base_resolver.py -v`
Expected: 3 passed.

- [ ] **Step 9: Commit**

```bash
git add streamload/utils/domain_resolver/factory.py streamload/services/base.py tests/utils/domain_resolver/test_factory.py tests/test_service_base_resolver.py
git commit -m "feat(services): route base_url through DomainResolver"
```

---

## Task 14: Wire resolver at app startup

**Files:**
- Modify: `streamload/cli/app.py`
- Modify: `streamload/services/__init__.py` (only if it constructs services — read first)

- [ ] **Step 1: Read CLI entry point**

```bash
grep -n "ServiceRegistry\|http_client\|HttpClient\|services\." streamload/cli/app.py | head -30
```

Identify the place where services are instantiated and the `HttpClient` is available.

- [ ] **Step 2: Inject resolver after instantiation**

At the point where each registered service is constructed (e.g., after `service_class(http)`), insert:

```python
from streamload.utils.domain_resolver.factory import build_resolver

resolver = build_resolver(
    http=http,
    config_overrides={
        sn: sec.get("base_url", "")
        for sn, sec in cfg.services.items()
    },
    probe_seeds={
        sc.short_name: sc.domains
        for sc in ServiceRegistry.all()
    },
    cache_path=Path("data/domains_cache.json"),
    repo="alfanowski/Streamload",
    branch="main",
)
for service_instance in instantiated_services:
    service_instance.attach_resolver(resolver)
```

(Adapt to actual variable names found in step 1.)

- [ ] **Step 3: Smoke test**

Run:
```bash
venv/bin/python -c "from streamload.utils.domain_resolver.factory import build_resolver; print('ok')"
venv/bin/pytest -q
```
Expected: full suite passes.

- [ ] **Step 4: Commit**

```bash
git add streamload/cli/app.py streamload/services/__init__.py
git commit -m "feat(cli): build and attach DomainResolver to services at startup"
```

---

## Task 15: Signing tool

**Files:**
- Create: `tools/__init__.py`
- Create: `tools/sign_domains.py`
- Create: `tests/test_sign_domains_tool.py`

- [ ] **Step 1: Write failing test**

`tests/test_sign_domains_tool.py`:
```python
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def test_sign_creates_valid_signature(tmp_path: Path):
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path = tmp_path / "k.pem"
    key_path.write_bytes(priv_pem)

    manifest_path = tmp_path / "domains.json"
    payload = {
        "schema_version": 1,
        "key_id": "x",
        "issued_at": "2026-05-05T00:00:00Z",
        "ttl_seconds": 60,
        "services": {},
    }
    manifest_path.write_text(json.dumps(payload, sort_keys=True))

    out = subprocess.run(
        [sys.executable, "tools/sign_domains.py",
         "--key", str(key_path),
         "--manifest", str(manifest_path)],
        capture_output=True, text=True, check=True,
    )
    sig_path = manifest_path.with_suffix(manifest_path.suffix + ".sig")
    assert sig_path.exists()

    sig = base64.b64decode(sig_path.read_text().strip())
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    Ed25519PublicKey.from_public_bytes(pub_raw).verify(sig, manifest_path.read_bytes())
```

- [ ] **Step 2: Run — fails**

Run: `venv/bin/pytest tests/test_sign_domains_tool.py -v`
Expected: FAIL — tool missing.

- [ ] **Step 3: Implement `tools/sign_domains.py`**

`tools/__init__.py`: empty file.

`tools/sign_domains.py`:
```python
"""Sign domains.json with the Ed25519 private key.

Usage::

    python tools/sign_domains.py --key secret/domains_signing_key.pem \\
                                 --manifest domains.json

Output: writes ``<manifest>.sig`` containing base64-encoded signature.
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--key", required=True, type=Path,
                   help="Path to PEM-encoded Ed25519 private key")
    p.add_argument("--manifest", required=True, type=Path,
                   help="Path to domains.json")
    args = p.parse_args(argv)

    priv_obj = serialization.load_pem_private_key(args.key.read_bytes(), password=None)
    if not isinstance(priv_obj, Ed25519PrivateKey):
        print("ERROR: key is not Ed25519", file=sys.stderr)
        return 2

    payload = args.manifest.read_bytes()
    sig = priv_obj.sign(payload)
    sig_b64 = base64.b64encode(sig).decode("ascii")

    sig_path = args.manifest.with_suffix(args.manifest.suffix + ".sig")
    sig_path.write_text(sig_b64 + "\n")
    print(f"wrote {sig_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run — passes**

Run: `venv/bin/pytest tests/test_sign_domains_tool.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/__init__.py tools/sign_domains.py tests/test_sign_domains_tool.py
git commit -m "tools: add Ed25519 signer for domains manifest"
```

---

## Task 16: Initial signed manifest

**Files:**
- Create: `domains.json`
- Create: `domains.json.sig`

- [ ] **Step 1: Write `domains.json`**

```json
{
  "issued_at": "2026-05-05T00:00:00Z",
  "key_id": "sl-2026-05-53b1aa",
  "schema_version": 1,
  "services": {
    "sc": {
      "fallbacks": ["streamingcommunity.prof", "streamingcommunity.computer"],
      "primary": "streamingcommunityz.nl"
    }
  },
  "ttl_seconds": 21600
}
```

(Keys sorted; this is what the signer hashes — must remain byte-identical between sign and verify.)

- [ ] **Step 2: Sign it**

```bash
venv/bin/python tools/sign_domains.py --key secret/domains_signing_key.pem --manifest domains.json
```

Expected: prints `wrote domains.json.sig`.

- [ ] **Step 3: Sanity-check verification**

```bash
venv/bin/python -c "
import base64, json
from streamload.utils.domain_resolver.signature import verify_manifest
from streamload.utils.domain_resolver.trusted_keys import TRUSTED_KEYS
body = open('domains.json','rb').read()
sig = open('domains.json.sig').read().strip()
key_id = json.loads(body)['key_id']
verify_manifest(body, sig, key_id=key_id, trusted_keys=TRUSTED_KEYS)
print('OK')
"
```
Expected: prints `OK`.

- [ ] **Step 4: Commit**

```bash
git add domains.json domains.json.sig
git commit -m "feat: initial signed domains manifest for sc service"
```

---

## Task 17: CLI `streamload domains` subcommand

**Files:**
- Modify: `streamload/cli/app.py` (add `domains` argparse subcommand)
- Create: `streamload/cli/commands/__init__.py` (only if not present — check first)
- Create: `streamload/cli/commands/domains.py`
- Create: `tests/test_cli_domains.py`

- [ ] **Step 1: Check existing CLI structure**

```bash
grep -n "argparse\|subparsers\|ArgumentParser\|add_subparsers" streamload/cli/app.py | head
```

Note the pattern (subparsers vs single command).

- [ ] **Step 2: Write failing test**

`tests/test_cli_domains.py`:
```python
from __future__ import annotations

from pathlib import Path

from streamload.cli.commands.domains import cmd_status, cmd_pin, cmd_refresh
from streamload.utils.domain_resolver.cache import DomainCache


def test_status_prints_no_entries(tmp_path: Path, capsys):
    cache = DomainCache(tmp_path / "c.json")
    cmd_status(cache=cache)
    out = capsys.readouterr().out
    assert "no cached domains" in out.lower()


def test_status_prints_each_cached_entry(tmp_path: Path, capsys):
    cache = DomainCache(tmp_path / "c.json")
    cache.set("sc", domain="x.tld", source="remote-github", validated_at=100.0)
    cmd_status(cache=cache)
    out = capsys.readouterr().out
    assert "sc" in out and "x.tld" in out and "remote-github" in out


def test_pin_writes_override_to_config_dict():
    cfg = {}
    cmd_pin(config=cfg, short_name="sc", url="https://my.tld")
    assert cfg["services"]["sc"]["base_url"] == "https://my.tld"


def test_refresh_invalidates_cache(tmp_path: Path):
    cache = DomainCache(tmp_path / "c.json")
    cache.set("sc", domain="x.tld", source="cache", validated_at=1.0)
    cmd_refresh(cache=cache, short_name="sc")
    assert cache.get("sc") is None
```

- [ ] **Step 3: Run — fails**

Run: `venv/bin/pytest tests/test_cli_domains.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement `streamload/cli/commands/domains.py`**

Create `streamload/cli/commands/__init__.py` if missing (empty file).

```python
"""CLI handlers for the `streamload domains` subcommand."""
from __future__ import annotations

from datetime import datetime, timezone

from streamload.utils.domain_resolver.cache import DomainCache


def cmd_status(*, cache: DomainCache) -> None:
    data = cache._read()  # internal read is fine -- same package
    entries = data.get("entries", {})
    if not entries:
        print("no cached domains")
        return
    print(f"{'service':10} {'domain':40} {'source':18} {'validated_at'}")
    for short_name, e in sorted(entries.items()):
        ts = datetime.fromtimestamp(e.get("validated_at", 0), tz=timezone.utc).isoformat()
        print(f"{short_name:10} {e.get('domain',''):40} {e.get('source',''):18} {ts}")


def cmd_refresh(*, cache: DomainCache, short_name: str | None) -> None:
    if short_name:
        cache.invalidate(short_name)
        print(f"invalidated {short_name}")
        return
    data = cache._read()
    for sn in list(data.get("entries", {}).keys()):
        cache.invalidate(sn)
    print("invalidated all")


def cmd_pin(*, config: dict, short_name: str, url: str) -> None:
    config.setdefault("services", {}).setdefault(short_name, {})["base_url"] = url
    print(f"pinned {short_name} -> {url}")
```

- [ ] **Step 5: Wire into argparse in `streamload/cli/app.py`**

Following the existing subparser pattern, add a `domains` subcommand with `status`, `refresh [<service>]`, and `pin <service> <url>` actions. Each calls the corresponding `cmd_*` function and persists `config.json` after `pin`.

- [ ] **Step 6: Run — passes**

Run: `venv/bin/pytest tests/test_cli_domains.py -v`
Expected: 4 passed.

- [ ] **Step 7: Smoke test**

```bash
venv/bin/python streamload.py domains status
```
Expected: prints `no cached domains` (or the manifest's first resolved entry if startup ran).

- [ ] **Step 8: Commit**

```bash
git add streamload/cli/commands/ streamload/cli/app.py tests/test_cli_domains.py
git commit -m "feat(cli): add `streamload domains` status/refresh/pin"
```

---

## Task 18: Hook record_failure into HTTP error path

**Files:**
- Modify: `streamload/services/base.py` (add helper)
- Modify: `streamload/services/streamingcommunity/scraper.py` (call helper on key errors) — optional, defer if scope creep

- [ ] **Step 1: Add helper to ServiceBase**

In `streamload/services/base.py`, add:

```python
def report_domain_failure(self) -> None:
    """Tell the resolver this service's current domain may be dead.

    Call from service code when a request fails in a way consistent with
    domain rotation (DNS error, repeated 403, redirect to parking page).
    """
    resolver = getattr(self, "_resolver", None)
    if resolver is None:
        return
    resolver.record_failure(self.short_name)
    # Force re-resolution next time base_url is read.
    self._resolved_domain = None
```

- [ ] **Step 2: Smoke test**

```bash
venv/bin/pytest -q
```
Expected: full suite passes.

- [ ] **Step 3: Commit**

```bash
git add streamload/services/base.py
git commit -m "feat(services): report_domain_failure helper for in-session recovery"
```

---

## Task 19: Documentation

**Files:**
- Modify: `README.md`
- Create: `docs/domain-resolver.md`

- [ ] **Step 1: Add resolver section to README**

Add a "Domain Rotation" section under features explaining: domains rotate, resolver handles it transparently, signed manifest, override via config, `streamload domains` CLI.

- [ ] **Step 2: Create operator guide**

`docs/domain-resolver.md` covers:
- How the chain resolves a domain
- How to update `domains.json` (edit, sign, commit, push)
- How to rotate the signing key (generate new, add to `trusted_keys.py`, ship release, then remove old after grace period)
- How to debug resolution issues using `streamload domains status` and the log

- [ ] **Step 3: Commit**

```bash
git add README.md docs/domain-resolver.md
git commit -m "docs: add domain resolver operator guide"
```

---

## Self-review checklist

Run after the engineer (or you) finishes Task 19:

- [ ] All 19 tasks completed and committed
- [ ] `venv/bin/pytest -q` shows all green
- [ ] `venv/bin/python streamload.py domains status` runs without error
- [ ] `domains.json` and `domains.json.sig` are committed and verify locally
- [ ] `secret/` is gitignored and contains `domains_signing_key.pem`
- [ ] No `Co-Authored-By` trailers in any commit on this branch
- [ ] `streamload.log` shows a "Resolved sc -> ..." line on first run

---

## Open issues (post-MVP, not in scope here)

- Background async manifest refresh on a timer (currently fetched lazily once per process)
- Multiple concurrent `lang` validators when service supports >1 language
- Telemetry / metrics export (counter on each resolve by source)
- Repository hosting of `domains.json` in a separate read-only repo to reduce attack surface
- Cloudflare Worker as a third independent route (deferred — jsDelivr already gives second route)
