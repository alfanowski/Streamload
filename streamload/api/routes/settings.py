"""Per-user preferences (stub for v1 — not persisted)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from streamload.api.deps import CurrentUser

router = APIRouter(prefix="/settings", tags=["settings"])


class UserSettings(BaseModel):
    audio_pref: str = "ita"
    subs_pref: str = "ita"
    autoplay_next: bool = True
    quality_lock: str | None = None


@router.get("", response_model=UserSettings)
async def get_settings(user: CurrentUser) -> UserSettings:
    """Return default settings. Plan 6 will persist in users.settings JSONB."""
    return UserSettings()


@router.put("", response_model=UserSettings)
async def update_settings(payload: UserSettings, user: CurrentUser) -> UserSettings:
    """Accept settings payload and echo back. Plan 6 will persist."""
    return payload
