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
