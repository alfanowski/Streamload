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
