# Domain Resolver — Operator Guide

This guide covers the internals of Streamload's domain resolution system and the workflows an operator needs when a streaming site rotates its domain.

---

## Architecture overview

Domain resolution follows a strict priority chain. Each source is consulted in order, and the first one that returns a valid, probed URL wins:

```
Config  →  Cache  →  Remote (GitHub raw / jsDelivr)  →  Probe
```

**Config source** (`config_source.py`) — reads `services.<short_name>.base_url` from `config.json`. If an operator has pinned a URL here, resolution stops immediately and no network traffic is generated.

**Cache source** (`cache_source.py`) — reads a file-backed cache stored under the platform cache directory. Entries carry a 6-hour TTL. If a cached entry is still fresh, resolution stops here.

**Remote source** (`remote_source.py`) — fetches `domains.json` from GitHub raw, falling back to a jsDelivr CDN mirror. The downloaded manifest must carry a valid Ed25519 signature issued by a key listed in `trusted_keys.py`; manifests with missing or invalid signatures are rejected and the next source is tried. On success the resolved domain is written back to the cache.

**Probe source** (`probe_source.py`) — contains a hardcoded list of known domains compiled from the service classes. It is the last resort and requires no network access to determine candidates, though each candidate is still validated before being returned.

**Active validation** (`validator.py`) — before any URL is returned to the caller, the resolver performs an HTTP GET and inspects the response. For StreamingCommunity it confirms the presence of the Inertia.js application structure. Parking pages, ISP hijack pages, and connection timeouts all cause the candidate to be rejected.

**Circuit breaker** (`circuit_breaker.py`) — if the remote source fails repeatedly within a short window, the circuit opens and remote fetches are skipped for a cooldown period. This prevents thundering-herd behaviour when a CDN is degraded.

All resolution code lives in `streamload/utils/domain_resolver/`.

---

## Resolving a domain

At application startup, each service calls the resolver once. The resolver walks the source chain described above and returns the first URL that passes active validation.

1. If `config.json` carries a pinned `base_url` for the service, that URL is returned after validation. No cache or remote access occurs.
2. The cache is read. If a valid, non-expired entry exists (TTL = 6 hours), that URL is validated and returned.
3. The remote source fetches `domains.json` from GitHub raw (`https://raw.githubusercontent.com/alfanowski/Streamload/main/domains.json`) and verifies the Ed25519 signature against the public keys in `trusted_keys.py`. If verification passes, the manifest's domain list for the service is iterated until a domain passes active validation. The winning URL is written to the cache with a fresh TTL.
4. If the remote source fails (network error, bad signature, all domains fail validation), the probe source iterates its hardcoded list and validates each candidate in turn.
5. If every source and every candidate fail, a `DomainResolutionError` is raised and the service is marked unavailable for the session.

The active validation step (`validator.py`) makes an HTTP GET with a realistic User-Agent and a short timeout. For StreamingCommunity it looks for the `<div id="app">` element and the `data-page` attribute that Inertia.js emits. Responses that do not match this shape are treated as failed.

---

## Updating the domain list (operator workflow)

When a streaming site rotates its domain, follow these steps to publish the updated manifest.

**1. Edit `domains.json`.**

Open `domains.json` in the repository root. Find the entry for the affected service and replace the stale domain with the new one. Keep the top-level keys sorted alphabetically -- the signing tool hashes the raw bytes, so byte-level stability matters. Increment the `issued_at` timestamp to a value larger than the current one (Unix seconds is conventional).

**2. Sign the manifest.**

```bash
venv/bin/python tools/sign_domains.py \
    --key secret/domains_signing_key.pem \
    --manifest domains.json
```

The script writes `domains.json.sig` next to the manifest. Both files must be committed together.

**3. Verify locally.**

Run a forced re-resolution to confirm the new domain is accepted:

```bash
python streamload-domains.py refresh
python streamload-domains.py status
```

You should see the new domain listed as the active URL for the affected service, and no "Manifest rejected" warnings in `streamload.log`.

**4. Commit and push.**

```bash
git add domains.json domains.json.sig
git commit -m "domains: update <service> domain to <new-domain>"
git push
```

Once the commit lands on `main`, GitHub raw and the jsDelivr mirror will serve the updated manifest within a few minutes. Clients with an expired cache will pick up the new domain on their next startup.

---

## Rotating the signing key

Rotate the signing key when the private key is believed to be compromised, or as a routine security measure.

**1. Generate a new keypair.**

Move or delete the existing `secret/domains_signing_key.pem`, then run:

```bash
venv/bin/python secret/_generate_key.py
```

This produces a new `domains_signing_key.pem` (private) and `domains_signing_key.pub.b64` (public, Base64-encoded).

**2. Add the new public key to `trusted_keys.py`.**

Open `streamload/utils/domain_resolver/trusted_keys.py`. Add a new entry to `TRUSTED_KEYS` using a new `key_id` string (e.g. `"v2"`). Paste the Base64-encoded public key from `domains_signing_key.pub.b64` as its value.

**3. Keep the old key for one release cycle.**

Do not remove the previous key_id from `TRUSTED_KEYS` yet. Existing clients running the previous release still carry only the old public key, and they must be able to verify the manifest during the transition window.

**4. Update `CURRENT_KEY_ID`.**

Change the `CURRENT_KEY_ID` constant in `trusted_keys.py` to the new key_id. The signing tool reads this constant to know which key_id to embed in the manifest.

**5. Re-sign the manifest with the new private key.**

```bash
venv/bin/python tools/sign_domains.py \
    --key secret/domains_signing_key.pem \
    --manifest domains.json
```

Commit `domains.json.sig`, `trusted_keys.py`, and any other changed files together.

**6. Remove the old key_id after clients upgrade.**

Once a release containing the new `trusted_keys.py` has been distributed and enough time has passed for users to update, remove the old key_id entry from `TRUSTED_KEYS`. Clients still on the old release without the new public key will fall through to the probe source, which requires no signature.

---

## Debugging

**Check current cache state**

```bash
python streamload-domains.py status
```

Prints the cached URL for each service along with its expiry time.

**Force re-resolution**

```bash
python streamload-domains.py refresh
```

Clears the cache entries and re-resolves all services from scratch. Useful after publishing an updated `domains.json` or when investigating a stale cache.

**Emergency override for a single service**

```bash
python streamload-domains.py pin sc https://streamingcommunity.example
```

Writes the given URL directly to the cache for the named service, bypassing signature verification and active validation. Intended for short-term incident response. The override persists until the TTL expires or another `refresh` is run. For a permanent override, set `base_url` in `config.json` instead.

**Log inspection**

The main log file is `streamload.log`. Useful patterns to search for:

- `Resolved sc ->` — successful resolution, shows which source won.
- `Manifest from ... rejected` — signature verification failed for the named source URL.
- `Domain ... failed validation` — a candidate was reached but did not match the expected page shape.
- `Circuit breaker open` — the remote source has been skipped due to repeated failures; waits for the cooldown period to expire.

---

## Trust model

`domains.json` is a file in this public repository. Without a signature, anyone with write access to the repository (or to the jsDelivr mirror) could substitute a malicious domain. The Ed25519 signature is the trust anchor: only operators in possession of `secret/domains_signing_key.pem` can produce a valid manifest.

Clients embed the corresponding public key in `trusted_keys.py`. At resolution time they verify the signature before accepting any domain from the manifest. A manifest with a missing, malformed, or invalid signature is rejected entirely and the resolver walks to the next source.

The jsDelivr CDN mirror serves the same signed bytes that are committed to the repository. A compromise of jsDelivr alone cannot result in a malicious domain being accepted, because the attacker cannot forge a valid signature without the private key.

The probe source uses a hardcoded list compiled from the service classes at build time. It accepts no network input, so it cannot be influenced by a remote attacker.

---

## Limitations

**Windows — cache file locking.** The cache uses `fcntl` for process-level file locking, which is not available on Windows. Concurrent Streamload instances on Windows may race on cache writes. In practice this is rare because Streamload is typically run as a single process, but operators running automated batch jobs on Windows should be aware of this.

**Validator shape coverage.** The active validator currently implements the Inertia.js shape check used by StreamingCommunity. Future services that use a different page structure will need a corresponding `shape` parameter added to `validator.py`. Until that is implemented, those services fall back to a basic HTTP 200 check.
