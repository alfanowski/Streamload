"""FastAPI dependencies for DB session, current user, admin gate."""
from __future__ import annotations

from typing import Annotated, AsyncIterator

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.auth.sessions import get_session_user_id, refresh_session
from streamload.db import get_session
from streamload.db.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    db: SessionDep,
    session: str | None = Cookie(default=None, alias="session"),
) -> User:
    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    user_id = await get_session_user_id(db, token=session)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired session")
    await refresh_session(db, token=session)
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
    return u


async def get_optional_user(
    db: SessionDep,
    session: str | None = Cookie(default=None, alias="session"),
) -> User | None:
    if not session:
        return None
    user_id = await get_session_user_id(db, token=session)
    if user_id is None:
        return None
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
AdminUser = Annotated[User, Depends(require_admin)]
