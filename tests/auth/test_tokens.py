"""Random token generation + hashing."""
from __future__ import annotations

from streamload.auth.tokens import generate_token, hash_token


def test_generate_token_length():
    tok = generate_token()
    assert isinstance(tok, str)
    assert 40 <= len(tok) <= 60


def test_generate_tokens_are_unique():
    seen = {generate_token() for _ in range(100)}
    assert len(seen) == 100


def test_hash_token_is_deterministic():
    tok = "abc"
    assert hash_token(tok) == hash_token(tok)


def test_hash_token_returns_32_bytes():
    h = hash_token("abc")
    assert isinstance(h, bytes)
    assert len(h) == 32


def test_hash_token_differs_per_input():
    assert hash_token("abc") != hash_token("abd")
