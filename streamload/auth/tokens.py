"""Random token generation and hashing.

Tokens are 32 random bytes encoded as urlsafe-base64 (~43 chars). Stored
hashed using SHA-256 so a DB compromise does not expose live tokens.
"""
from __future__ import annotations

import hashlib
import secrets


def generate_token(num_bytes: int = 32) -> str:
    """Generate a urlsafe random token. Default 32 bytes (~43 chars)."""
    return secrets.token_urlsafe(num_bytes)


def hash_token(token: str) -> bytes:
    """SHA-256 of token, used for at-rest storage and lookup."""
    return hashlib.sha256(token.encode("utf-8")).digest()
