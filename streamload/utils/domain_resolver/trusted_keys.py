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
