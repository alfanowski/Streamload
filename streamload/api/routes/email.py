"""Email verification + password reset endpoints."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import SessionDep
from streamload.auth.email_tokens import consume_token
from streamload.db.models import User

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
