"""Email verification + password reset endpoints."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select

from streamload.api.deps import SessionDep
from streamload.auth.email_tokens import consume_token, issue_token
from streamload.auth.passwords import hash_password
from streamload.db.models import Session as SessionModel, User
from streamload.email import build_email_client
from streamload.email.templates import password_reset_email

router = APIRouter(prefix="/auth", tags=["email"])


class VerifyRequest(BaseModel):
    token: str


@router.post("/verify-email", status_code=200)
async def verify_email(payload: VerifyRequest, db: SessionDep) -> dict[str, str]:
    user_id = await consume_token(db, token=payload.token, purpose="verify_email")
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired token")
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user not found")
    u.email_verified_at = datetime.now(UTC)
    await db.commit()
    return {"status": "verified"}


class RequestResetRequest(BaseModel):
    email: EmailStr


class ConfirmResetRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/request-password-reset", status_code=200)
async def request_password_reset(
    payload: RequestResetRequest,
    db: SessionDep,
    request: Request,
) -> dict[str, str]:
    """Issue a password-reset token and email it.

    Always returns 200 regardless of whether the email is registered
    (anti-enumeration: callers cannot distinguish existing from unknown users).
    """
    u = (await db.execute(
        select(User).where(User.email == str(payload.email).lower())
    )).scalar_one_or_none()

    if u is not None:
        tok = await issue_token(db, user_id=u.id, purpose="reset_password")
        base = str(request.base_url).rstrip("/")
        link = f"{base}/reset?token={tok}"
        client = build_email_client()
        subject, html, text = password_reset_email(username=u.username, link=link)
        try:
            await client.send(to=u.email, subject=subject, html=html, text=text)
        except Exception:
            pass  # Do not leak errors — still return 200.

    return {"status": "ok"}


@router.post("/confirm-password-reset", status_code=200)
async def confirm_password_reset(
    payload: ConfirmResetRequest,
    db: SessionDep,
) -> dict[str, str]:
    """Consume a reset token, update the password, and invalidate all sessions."""
    user_id = await consume_token(db, token=payload.token, purpose="reset_password")
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired token")

    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user not found")

    u.password_hash = hash_password(payload.new_password)

    # Invalidate all existing sessions for this user.
    await db.execute(delete(SessionModel).where(SessionModel.user_id == user_id))

    await db.commit()
    return {"status": "ok"}
