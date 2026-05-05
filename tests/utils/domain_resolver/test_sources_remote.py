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
