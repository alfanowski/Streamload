"""WebAuthn passkey endpoints."""
from __future__ import annotations

import base64
import json

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import CurrentUser, SessionDep
from streamload.api.telemetry import emit as emit_event
from streamload.auth.passkeys import (
    make_authentication_options,
    make_registration_options,
    verify_authentication,
    verify_registration,
)
from streamload.auth.sessions import create_session
from streamload.db.models import User, WebauthnCredential

router = APIRouter(prefix="/auth/passkey", tags=["passkey"])


class RegistrationOptionsRequest(BaseModel):
    nickname: str | None = None


@router.post("/registration-options")
async def registration_options(
    payload: RegistrationOptionsRequest,
    user: CurrentUser,
    db: SessionDep,
) -> dict:
    existing = (
        await db.execute(
            select(WebauthnCredential.credential_id).where(
                WebauthnCredential.user_id == user.id
            )
        )
    ).scalars().all()
    options_json = make_registration_options(
        user_id=user.id,
        username=user.username,
        existing_credential_ids=list(existing),
    )
    return json.loads(options_json)


class RegistrationVerifyRequest(BaseModel):
    response: dict
    nickname: str | None = None


@router.post("/registration-verify")
async def registration_verify(
    payload: RegistrationVerifyRequest,
    user: CurrentUser,
    db: SessionDep,
    request: Request,
) -> dict[str, str]:
    try:
        cred_id, pub_key, transports = verify_registration(
            user_id=user.id,
            response_json=payload.response,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    db.add(
        WebauthnCredential(
            user_id=user.id,
            credential_id=cred_id,
            public_key=pub_key,
            transports=transports,
            nickname=payload.nickname,
        )
    )
    await emit_event(db, request, user_id=user.id, event_type="auth.passkey_register")
    await db.commit()
    return {"status": "registered"}


class AuthOptionsRequest(BaseModel):
    username: str


@router.post("/authentication-options")
async def authentication_options(payload: AuthOptionsRequest, db: SessionDep) -> dict:
    user = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    if user is None:
        # Anti-enumeration: still return a decoy options object
        options_json = make_authentication_options(
            allowed_credential_ids=[],
            username_hint=payload.username,
        )
        return json.loads(options_json)
    creds = (
        await db.execute(
            select(WebauthnCredential.credential_id).where(
                WebauthnCredential.user_id == user.id
            )
        )
    ).scalars().all()
    options_json = make_authentication_options(
        allowed_credential_ids=list(creds),
        username_hint=payload.username,
    )
    return json.loads(options_json)


class AuthVerifyRequest(BaseModel):
    username: str
    response: dict


@router.post("/authentication-verify")
async def authentication_verify(
    payload: AuthVerifyRequest,
    db: SessionDep,
    request: Request,
    response: Response,
):
    user = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    cred_id_b64 = payload.response.get("rawId") or payload.response.get("id")
    if not cred_id_b64:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing credential id")
    cred_id = base64.urlsafe_b64decode(
        cred_id_b64 + "=" * (-len(cred_id_b64) % 4)
    )
    cred = (
        await db.execute(
            select(WebauthnCredential)
            .where(WebauthnCredential.user_id == user.id)
            .where(WebauthnCredential.credential_id == cred_id)
        )
    ).scalar_one_or_none()
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "credential not registered")
    try:
        new_count = verify_authentication(
            username_hint=payload.username,
            response_json=payload.response,
            credential_public_key=cred.public_key,
            sign_count=cred.sign_count,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "verification failed") from exc
    cred.sign_count = new_count
    await db.commit()

    token = await create_session(db, user_id=user.id)
    response.set_cookie(
        "session",
        token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return {"status": "authenticated"}
