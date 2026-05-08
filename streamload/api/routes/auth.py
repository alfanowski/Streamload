"""Auth endpoints: register, login, logout."""
from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from streamload.api.deps import SessionDep
from streamload.auth.email_tokens import issue_token
from streamload.auth.passwords import hash_password, verify_password
from streamload.auth.rate_limit import RateLimiter
from streamload.auth.sessions import create_session, delete_session
from streamload.db.models import User
from streamload.email.client import EmailClient
from streamload.email.templates import verification_email
from streamload.utils.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_login_limiter_per_ip = RateLimiter(rate=10, per_seconds=300)
_login_limiter_per_user = RateLimiter(rate=5, per_seconds=300)


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


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)  # accepts username OR email
    password: str = Field(min_length=1, max_length=128)


@router.post("/login", status_code=200, response_model=UserPublic)
async def login(payload: LoginRequest, db: SessionDep, response: Response, request: Request) -> UserPublic:
    ip_key = request.client.host if request.client else "unknown"
    user_key = payload.username.lower()
    if not _login_limiter_per_ip.check(ip_key) or not _login_limiter_per_user.check(user_key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many login attempts")

    stmt = select(User).where((User.username == payload.username) | (User.email == payload.username.lower()))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not user.password_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if not verify_password(user.password_hash, payload.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    user.last_login_at = datetime.now(UTC)
    await db.commit()

    token = await create_session(
        db, user_id=user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    response.set_cookie(
        "session", token,
        httponly=True, secure=request.url.scheme == "https",
        samesite="lax", max_age=60 * 60 * 24 * 30,
    )
    return _user_to_public(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: SessionDep) -> None:
    token = request.cookies.get("session")
    if token:
        await delete_session(db, token=token)
    response.delete_cookie("session")
