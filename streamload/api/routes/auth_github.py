"""POST /api/auth/github — exchange a GitHub access token for a backend session."""
from __future__ import annotations

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from streamload.api.deps import SessionDep
from streamload.api.routes.auth import UserPublic, _user_to_public
from streamload.api.telemetry import emit as emit_event
from streamload.auth.github import fetch_github_profile
from streamload.auth.sessions import create_session
from streamload.db.models import User
from streamload.utils.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class GithubLoginRequest(BaseModel):
    access_token: str


@router.post("/github", status_code=200, response_model=UserPublic)
async def github_login(
    payload: GithubLoginRequest,
    db: SessionDep,
    response: Response,
    request: Request,
) -> UserPublic:
    async with httpx.AsyncClient(
        base_url="https://api.github.com", timeout=15
    ) as gh:
        try:
            profile = await fetch_github_profile(token=payload.access_token, http=gh)
        except ValueError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e))

    # Find by github_id.
    user = (await db.execute(
        select(User).where(User.github_id == profile.id)
    )).scalar_one_or_none()

    if user is None:
        # Username must be unique; if profile.login collides with a legacy
        # password user, suffix with the github_id.
        username = profile.login
        existing = (await db.execute(
            select(User).where(User.username == username)
        )).scalar_one_or_none()
        if existing is not None:
            username = f"{profile.login}_{profile.id}"
        user = User(
            username=username,
            email=profile.email,
            password_hash=None,
            github_id=profile.id,
            github_username=profile.login,
            email_verified_at=datetime.now(UTC),
            email_required=False,
            role="user",
            profile_complete=False,
        )
        db.add(user)
        try:
            await db.commit()
            await db.refresh(user)
        except IntegrityError as e:
            await db.rollback()
            log.exception("github user create failed")
            raise HTTPException(status.HTTP_409_CONFLICT, str(e))
        await emit_event(db, request, user_id=user.id, event_type="auth.github_register",
                         payload={"github_id": profile.id})
        await db.commit()
    else:
        # Returning user — keep email + login fresh.
        user.github_username = profile.login
        user.email = profile.email
        await db.commit()
        await emit_event(db, request, user_id=user.id, event_type="auth.github_login",
                         payload={"github_id": profile.id})
        await db.commit()

    token = await create_session(
        db,
        user_id=user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    response.set_cookie(
        "session", token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return _user_to_public(user)
