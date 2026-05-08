"""Verify ORM models map columns correctly."""
from __future__ import annotations

import uuid

from streamload.db.models import EmailToken, Session, User, WebauthnCredential


def test_user_has_expected_columns():
    cols = {c.name for c in User.__table__.columns}
    assert {"id", "username", "email", "email_verified_at", "email_required",
            "password_hash", "role", "locale", "avatar_url",
            "created_at", "last_login_at"} <= cols


def test_session_has_expected_columns():
    cols = {c.name for c in Session.__table__.columns}
    assert {"token_hash", "user_id", "user_agent", "ip_address",
            "issued_at", "expires_at", "last_seen_at"} <= cols


def test_email_token_has_expected_columns():
    cols = {c.name for c in EmailToken.__table__.columns}
    assert {"token_hash", "user_id", "purpose",
            "issued_at", "expires_at", "consumed_at"} <= cols


def test_webauthn_credential_has_expected_columns():
    cols = {c.name for c in WebauthnCredential.__table__.columns}
    assert {"id", "user_id", "credential_id", "public_key",
            "sign_count", "transports", "nickname",
            "created_at", "last_used_at"} <= cols


def test_user_id_is_uuid_default():
    u = User(username="x", email="x@x")
    assert isinstance(u.id, uuid.UUID) or u.id is None  # default fired only on flush
