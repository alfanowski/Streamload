"""WebAuthn / FIDO2 passkey ceremonies (registration + authentication).

Wraps the ``webauthn`` library with our DB models. Challenge state is
stored short-lived in the in-memory ``_challenge_store`` keyed by user_id
or username — for a single-instance deployment this is fine.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    UserVerificationRequirement,
)

CHALLENGE_TTL_SEC = 300


@dataclass
class _Stored:
    challenge: bytes
    expires_at: float
    user_id_hex: Optional[str] = None  # for registration: the user we're registering


_challenge_store: dict[str, _Stored] = {}


def _rp_id() -> str:
    return os.environ.get("WEBAUTHN_RP_ID", "localhost")


def _rp_name() -> str:
    return os.environ.get("WEBAUTHN_RP_NAME", "Streamload")


def _origin() -> str:
    return os.environ.get("WEBAUTHN_ORIGIN", "http://localhost:8000")


def make_registration_options(
    *,
    user_id: uuid.UUID,
    username: str,
    existing_credential_ids: list[bytes],
) -> str:
    options = generate_registration_options(
        rp_id=_rp_id(),
        rp_name=_rp_name(),
        user_id=user_id.bytes,
        user_name=username,
        user_display_name=username,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.PREFERRED,
            authenticator_attachment=None,
        ),
        supported_pub_key_algs=[
            COSEAlgorithmIdentifier.ECDSA_SHA_256,
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
        ],
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=cid) for cid in existing_credential_ids
        ],
    )
    _challenge_store[f"reg:{user_id}"] = _Stored(
        challenge=options.challenge,
        expires_at=time.time() + CHALLENGE_TTL_SEC,
        user_id_hex=user_id.hex,
    )
    return options_to_json(options)


def verify_registration(
    *,
    user_id: uuid.UUID,
    response_json: dict,
) -> tuple[bytes, bytes, list[str]]:
    """Verify the registration response. Return (credential_id, public_key, transports)."""
    key = f"reg:{user_id}"
    stored = _challenge_store.pop(key, None)
    if stored is None or stored.expires_at < time.time():
        raise ValueError("challenge expired or missing")
    verification = verify_registration_response(
        credential=response_json,
        expected_challenge=stored.challenge,
        expected_rp_id=_rp_id(),
        expected_origin=_origin(),
    )
    transports: list[str] = []
    response = response_json.get("response", {})
    if "transports" in response:
        transports = response["transports"]
    return verification.credential_id, verification.credential_public_key, transports


def make_authentication_options(
    *,
    allowed_credential_ids: list[bytes],
    username_hint: str,
) -> str:
    options = generate_authentication_options(
        rp_id=_rp_id(),
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=cid) for cid in allowed_credential_ids
        ],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    _challenge_store[f"auth:{username_hint}"] = _Stored(
        challenge=options.challenge,
        expires_at=time.time() + CHALLENGE_TTL_SEC,
    )
    return options_to_json(options)


def verify_authentication(
    *,
    username_hint: str,
    response_json: dict,
    credential_public_key: bytes,
    sign_count: int,
) -> int:
    """Verify and return the new sign_count."""
    key = f"auth:{username_hint}"
    stored = _challenge_store.pop(key, None)
    if stored is None or stored.expires_at < time.time():
        raise ValueError("challenge expired or missing")
    verification = verify_authentication_response(
        credential=response_json,
        expected_challenge=stored.challenge,
        expected_rp_id=_rp_id(),
        expected_origin=_origin(),
        credential_public_key=credential_public_key,
        credential_current_sign_count=sign_count,
    )
    return verification.new_sign_count
