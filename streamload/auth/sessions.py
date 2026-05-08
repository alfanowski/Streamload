"""Session lifecycle: create, lookup, refresh, delete.

Tokens are opaque 32-byte secrets returned to the client (HttpOnly cookie).
Only the SHA-256 hash is stored in the DB. Sessions have a sliding TTL:
last_seen_at + DEFAULT_TTL = effective expiry; refresh_session() updates
last_seen_at when the user makes an authenticated request.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db.models import Session as SessionModel

from .tokens import generate_token, hash_token

DEFAULT_SESSION_TTL = timedelta(days=30)
REFRESH_GRACE = timedelta(minutes=5)  # only update last_seen if older than this


async def create_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
    ttl: Optional[timedelta] = None,
) -> str:
    """Create a new session row, return the opaque token (give to client)."""
    token = generate_token()
    h = hash_token(token)
    now = datetime.now(UTC)
    expiry = now + (ttl if ttl is not None else DEFAULT_SESSION_TTL)
    db.add(SessionModel(
        token_hash=h,
        user_id=user_id,
        user_agent=user_agent,
        ip_address=ip_address,
        issued_at=now,
        expires_at=expiry,
        last_seen_at=now,
    ))
    await db.commit()
    return token


async def get_session_user_id(
    db: AsyncSession,
    *,
    token: str,
) -> Optional[uuid.UUID]:
    """Resolve a token to a user_id if the session is valid."""
    h = hash_token(token)
    stmt = select(SessionModel).where(SessionModel.token_hash == h)
    s = (await db.execute(stmt)).scalar_one_or_none()
    if s is None:
        return None
    if s.expires_at <= datetime.now(UTC):
        return None
    return s.user_id


async def refresh_session(db: AsyncSession, *, token: str) -> None:
    """Update last_seen_at if it's older than the grace window."""
    h = hash_token(token)
    stmt = select(SessionModel).where(SessionModel.token_hash == h)
    s = (await db.execute(stmt)).scalar_one_or_none()
    if s is None:
        return
    now = datetime.now(UTC)
    if now - s.last_seen_at >= REFRESH_GRACE:
        s.last_seen_at = now
        s.expires_at = now + DEFAULT_SESSION_TTL
        await db.commit()


async def delete_session(db: AsyncSession, *, token: str) -> None:
    """Delete a session row (logout)."""
    h = hash_token(token)
    stmt = select(SessionModel).where(SessionModel.token_hash == h)
    s = (await db.execute(stmt)).scalar_one_or_none()
    if s is not None:
        await db.delete(s)
        await db.commit()
