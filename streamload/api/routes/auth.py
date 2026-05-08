"""Auth endpoints: register, login, logout."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from streamload.api.deps import SessionDep
from streamload.auth.email_tokens import issue_token
from streamload.auth.passwords import hash_password
from streamload.auth.sessions import create_session
from streamload.db.models import User
from streamload.email.client import EmailClient
from streamload.email.templates import verification_email
from streamload.utils.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserPublic(BaseModel):
    id: str
    username: str
    email: str
    email_verified: bool
    role: str


def _user_to_public(u: User) -> UserPublic:
    return UserPublic(
        id=str(u.id),
        username=u.username,
        email=u.email,
        email_verified=u.email_verified_at is not None,
        role=u.role,
    )


def _build_email_client() -> EmailClient:
    """Best-effort email client from env. Falls back to dry-run when no API key."""
    api_key = os.environ.get("RESEND_API_KEY", "")
    from_addr = os.environ.get("RESEND_FROM", "noreply@resend.dev")
    if not api_key:
        return EmailClient(api_key="", from_address=from_addr, dry_run=True)
    return EmailClient(api_key=api_key, from_address=from_addr)


@router.post("/register", status_code=201, response_model=UserPublic)
async def register(
    payload: RegisterRequest,
    db: SessionDep,
    response: Response,
    request: Request,
) -> UserPublic:
    # Determine role: first user becomes admin.
    count = (await db.execute(select(func.count(User.id)))).scalar_one()
    role = "admin" if count == 0 else "user"

    user = User(
        username=payload.username,
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "username or email already in use")

    # Issue verification token + send email (dry-run if no API key set).
    tok = await issue_token(db, user_id=user.id, purpose="verify_email")
    base = str(request.base_url).rstrip("/")
    link = f"{base}/verify?token={tok}"
    client = _build_email_client()
    subject, html, text = verification_email(username=user.username, link=link)
    try:
        await client.send(to=user.email, subject=subject, html=html, text=text)
    except Exception:
        log.warning("Failed to send verification email", exc_info=True)
        # Do not fail registration if email is down.

    # Issue login session immediately.
    token = await create_session(
        db,
        user_id=user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    response.set_cookie(
        "session",
        token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return _user_to_public(user)
