"""Admin user management + system status endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import AdminUser, SessionDep
from streamload.db.models import User

router = APIRouter(prefix="/admin", tags=["admin"])


class UserSummary(BaseModel):
    id: str
    username: str
    email: str
    role: str
    email_verified: bool
    created_at: str


class PromoteRequest(BaseModel):
    role: str  # 'admin' | 'user'


@router.get("/users", response_model=list[UserSummary])
async def list_users(admin: AdminUser, db: SessionDep) -> list[UserSummary]:
    """List all users ordered by creation date."""
    rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return [
        UserSummary(
            id=str(u.id),
            username=u.username,
            email=u.email,
            role=u.role,
            email_verified=u.email_verified_at is not None,
            created_at=u.created_at.isoformat(),
        )
        for u in rows
    ]


@router.put("/users/{user_id}/role")
async def update_role(
    user_id: str,
    payload: PromoteRequest,
    admin: AdminUser,
    db: SessionDep,
) -> dict:
    """Promote or demote a user's role."""
    if payload.role not in ("admin", "user"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "role must be 'admin' or 'user'")
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    u.role = payload.role
    await db.commit()
    return {"status": "ok"}


@router.get("/health/domains")
async def domains_health(admin: AdminUser) -> dict:
    """Show resolver state per service: cached domain, source, last verified."""
    from pathlib import Path
    from streamload.utils.domain_resolver.cache import DomainCache
    cache = DomainCache(Path("data/domains_cache.json"))
    return {"entries": cache.entries()}
