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
