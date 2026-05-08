"""Password hashing + verification."""
from __future__ import annotations

import pytest

from streamload.auth.passwords import hash_password, needs_rehash, verify_password


def test_hash_password_returns_argon2_string():
    h = hash_password("hunter2")
    assert h.startswith("$argon2id$")


def test_verify_password_accepts_correct():
    h = hash_password("hunter2")
    assert verify_password(h, "hunter2") is True


def test_verify_password_rejects_wrong():
    h = hash_password("hunter2")
    assert verify_password(h, "wrong") is False


def test_verify_password_rejects_empty():
    h = hash_password("hunter2")
    assert verify_password(h, "") is False


def test_verify_password_rejects_bad_hash_format():
    assert verify_password("not-a-hash", "hunter2") is False


def test_hash_password_rejects_empty():
    with pytest.raises(ValueError):
        hash_password("")


def test_needs_rehash_for_old_params():
    weak_hash = "$argon2id$v=19$m=512,t=1,p=1$YWFh$YWFh"
    assert needs_rehash(weak_hash) is True
