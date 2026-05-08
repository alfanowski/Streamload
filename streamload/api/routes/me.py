"""Current-user endpoint."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from streamload.api.deps import CurrentUser

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
