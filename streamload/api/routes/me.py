"""Current-user endpoints."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from streamload.api.deps import CurrentUser, SessionDep
from streamload.api.routes.auth import UserPublic, _user_to_public
from streamload.db.models import Gender

router = APIRouter(tags=["users"])


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    email_verified: bool
    role: str
    locale: str

    class Config:
        from_attributes = True


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        role=user.role,
        locale=user.locale,
    )


class ProfilePatchRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=64)
    last_name: str = Field(min_length=1, max_length=64)
    birth_date: dt.date
    gender: str  # validated below

    @field_validator("birth_date")
    @classmethod
    def _not_future(cls, v: dt.date) -> dt.date:
        if v >= dt.date.today():
            raise ValueError("birth_date must be in the past")
        return v

    @field_validator("gender")
    @classmethod
    def _valid_gender(cls, v: str) -> str:
        if v not in {g.value for g in Gender}:
            raise ValueError(f"gender must be one of {[g.value for g in Gender]}")
        return v


@router.patch("/me/profile", status_code=200, response_model=UserPublic)
async def patch_profile(
    payload: ProfilePatchRequest,
    db: SessionDep,
    user: CurrentUser,
) -> UserPublic:
    user.first_name = payload.first_name
    user.last_name = payload.last_name
    user.birth_date = payload.birth_date
    user.gender = Gender(payload.gender)
    user.profile_complete = True
    await db.commit()
    await db.refresh(user)
    return _user_to_public(user)
