"""Password hashing using argon2id.

We use the OWASP-recommended parameters for argon2id (May 2025):
- memory: 64 MB
- iterations: 3
- parallelism: 4

These are reasonable for a 2-core Celeron server while still resistant
to GPU brute-force at the threat scale we care about (single-user, no
public exposure).
"""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Tuned for our hardware target.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # KiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must be non-empty")
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    if not password or not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """Return True if *stored_hash* uses outdated params."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
