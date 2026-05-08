"""Email tokens: issue, consume, purge.

Tokens are single-use. Issuing a new token for the same (user, purpose)
invalidates the previous unused one (replaces it). Tokens are stored as
SHA-256 hashes; the plaintext is only available at issuance time.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db.models import EmailToken

from .tokens import generate_token, hash_token

Purpose = Literal["verify_email", "reset_password"]

DEFAULT_TTL: dict[str, timedelta] = {
    "verify_email": timedelta(hours=24),
    "reset_password": timedelta(hours=1),
}


async def issue_token(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    purpose: Purpose,
    ttl: Optional[timedelta] = None,
) -> str:
    """Issue a new token, replacing any existing unused one for same (user, purpose)."""
    # Invalidate previous unused tokens of the same purpose for this user.
    await db.execute(
        delete(EmailToken)
        .where(EmailToken.user_id == user_id)
        .where(EmailToken.purpose == purpose)
        .where(EmailToken.consumed_at.is_(None))
    )
    token = generate_token()
    h = hash_token(token)
    now = datetime.now(UTC)
    db.add(EmailToken(
        token_hash=h,
        user_id=user_id,
        purpose=purpose,
        issued_at=now,
        expires_at=now + (ttl if ttl is not None else DEFAULT_TTL[purpose]),
    ))
    await db.commit()
    return token


async def consume_token(
    db: AsyncSession,
    *,
    token: str,
    purpose: Purpose,
) -> Optional[uuid.UUID]:
    """Verify + consume a token. Returns the user_id if valid, else None."""
    h = hash_token(token)
    stmt = select(EmailToken).where(EmailToken.token_hash == h)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    if row.purpose != purpose:
        return None
    if row.consumed_at is not None:
        return None
    if row.expires_at <= datetime.now(UTC):
        return None
    row.consumed_at = datetime.now(UTC)
    await db.commit()
    return row.user_id


async def purge_expired_tokens(db: AsyncSession) -> int:
    """Delete expired or consumed tokens older than 30 days. Return count."""
    cutoff = datetime.now(UTC) - timedelta(days=30)
    result = await db.execute(
        delete(EmailToken)
        .where(
            (EmailToken.expires_at < datetime.now(UTC)) |
            (EmailToken.consumed_at < cutoff)
        )
    )
    await db.commit()
    return result.rowcount or 0
