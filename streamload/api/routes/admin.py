"""Admin user management + system status endpoints."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from streamload.api.deps import AdminUser, SessionDep
from streamload.auth.passwords import hash_password
from streamload.db.models import (
    CatalogItem,
    Session,
    User,
    WatchProgress,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class UserSummary(BaseModel):
    id: str
    username: str
    email: str
    role: str
    email_verified: bool
    disabled: bool
    created_at: str
    last_login_at: Optional[str] = None


class PromoteRequest(BaseModel):
    role: str  # 'admin' | 'user'


class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class TopWatchedItem(BaseModel):
    tmdb_id: int
    title: str
    media_type: str
    poster_url: Optional[str]
    watchers: int


class CatalogStats(BaseModel):
    total_items: int
    total_users: int
    active_users: int
    disabled_users: int
    completed_views_30d: int


def _serialize_user(u: User) -> UserSummary:
    return UserSummary(
        id=str(u.id),
        username=u.username,
        email=u.email,
        role=u.role,
        email_verified=u.email_verified_at is not None,
        disabled=u.disabled_at is not None,
        created_at=u.created_at.isoformat(),
        last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
    )


@router.get("/users", response_model=list[UserSummary])
async def list_users(admin: AdminUser, db: SessionDep) -> list[UserSummary]:
    rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return [_serialize_user(u) for u in rows]


@router.put("/users/{user_id}/role")
async def update_role(
    user_id: str,
    payload: PromoteRequest,
    admin: AdminUser,
    db: SessionDep,
) -> dict:
    if payload.role not in ("admin", "user"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "role must be 'admin' or 'user'")
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")

    if payload.role == "user" and u.role == "admin":
        # Prevent demoting the last admin.
        admin_count = (await db.execute(
            select(func.count(User.id)).where(User.role == "admin")
        )).scalar_one()
        if admin_count <= 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "cannot demote the last admin",
            )

    u.role = payload.role
    await db.commit()
    return {"status": "ok"}


@router.post("/users/{user_id}/disable")
async def disable_user(user_id: str, admin: AdminUser, db: SessionDep) -> dict:
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if u.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot disable yourself")
    if u.role == "admin":
        admin_count = (await db.execute(
            select(func.count(User.id)).where(User.role == "admin")
        )).scalar_one()
        if admin_count <= 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "cannot disable the last admin",
            )

    u.disabled_at = datetime.now(UTC)
    # Revoke all sessions immediately.
    await db.execute(delete(Session).where(Session.user_id == u.id))
    await db.commit()
    return {"status": "ok"}


@router.post("/users/{user_id}/enable")
async def enable_user(user_id: str, admin: AdminUser, db: SessionDep) -> dict:
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    u.disabled_at = None
    await db.commit()
    return {"status": "ok"}


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    payload: ResetPasswordRequest,
    admin: AdminUser,
    db: SessionDep,
) -> dict:
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    u.password_hash = hash_password(payload.password)
    # Force re-login everywhere.
    await db.execute(delete(Session).where(Session.user_id == u.id))
    await db.commit()
    return {"status": "ok"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: AdminUser, db: SessionDep) -> dict:
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if u.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot delete yourself")
    if u.role == "admin":
        admin_count = (await db.execute(
            select(func.count(User.id)).where(User.role == "admin")
        )).scalar_one()
        if admin_count <= 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "cannot delete the last admin",
            )
    await db.delete(u)
    await db.commit()
    return {"status": "ok"}


@router.get("/stats", response_model=CatalogStats)
async def stats(admin: AdminUser, db: SessionDep) -> CatalogStats:
    from datetime import timedelta

    items = (await db.execute(select(func.count(CatalogItem.tmdb_id)))).scalar_one()
    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    active = (await db.execute(
        select(func.count(User.id)).where(User.disabled_at.is_(None))
    )).scalar_one()
    disabled = total_users - active

    cutoff = datetime.now(UTC) - timedelta(days=30)
    completed = (await db.execute(
        select(func.count())
        .select_from(WatchProgress)
        .where(WatchProgress.completed.is_(True))
        .where(WatchProgress.updated_at >= cutoff)
    )).scalar_one()

    return CatalogStats(
        total_items=items,
        total_users=total_users,
        active_users=active,
        disabled_users=disabled,
        completed_views_30d=completed,
    )


@router.get("/top-watched", response_model=list[TopWatchedItem])
async def top_watched(
    admin: AdminUser,
    db: SessionDep,
    limit: int = 20,
) -> list[TopWatchedItem]:
    """Most-watched titles across all users (distinct watchers per title)."""
    stmt = (
        select(
            CatalogItem.tmdb_id,
            CatalogItem.title,
            CatalogItem.media_type,
            CatalogItem.poster_url,
            func.count(func.distinct(WatchProgress.user_id)).label("watchers"),
        )
        .join(
            WatchProgress,
            (WatchProgress.tmdb_id == CatalogItem.tmdb_id)
            & (WatchProgress.media_type == CatalogItem.media_type),
        )
        .group_by(
            CatalogItem.tmdb_id,
            CatalogItem.title,
            CatalogItem.media_type,
            CatalogItem.poster_url,
        )
        .order_by(func.count(func.distinct(WatchProgress.user_id)).desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        TopWatchedItem(
            tmdb_id=r.tmdb_id,
            title=r.title,
            media_type=r.media_type,
            poster_url=r.poster_url,
            watchers=int(r.watchers),
        )
        for r in rows
    ]


