"""Per-user preferences — v3 DB-backed via user_settings table."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import UserSettings as UserSettingsRow

router = APIRouter(prefix="/settings", tags=["settings"])


Theme = Literal["auto", "light", "dark"]


class UserSettings(BaseModel):
    audio_pref_lang: str = "ita"
    subs_pref_lang: str = "ita"
    quality_cap_height: int | None = None
    autoplay_next_episode: bool = True
    skip_intro: bool = True
    theme: Theme = "auto"
    locale: str = "it-IT"


def _row_to_model(row: UserSettingsRow) -> UserSettings:
    return UserSettings(
        audio_pref_lang=row.audio_pref_lang,
        subs_pref_lang=row.subs_pref_lang,
        quality_cap_height=row.quality_cap_height,
        autoplay_next_episode=row.autoplay_next_episode,
        skip_intro=row.skip_intro,
        theme=row.theme,
        locale=row.locale,
    )


@router.get("", response_model=UserSettings)
async def get_settings(user: CurrentUser, db: SessionDep) -> UserSettings:
    row = (await db.execute(
        select(UserSettingsRow).where(UserSettingsRow.user_id == user.id)
    )).scalar_one_or_none()
    if row is None:
        # Defaults baked into UserSettings(); not persisted until PUT.
        return UserSettings()
    return _row_to_model(row)


@router.put("", response_model=UserSettings)
async def update_settings(
    payload: UserSettings, user: CurrentUser, db: SessionDep,
) -> UserSettings:
    stmt = insert(UserSettingsRow).values(
        user_id=user.id,
        audio_pref_lang=payload.audio_pref_lang,
        subs_pref_lang=payload.subs_pref_lang,
        quality_cap_height=payload.quality_cap_height,
        autoplay_next_episode=payload.autoplay_next_episode,
        skip_intro=payload.skip_intro,
        theme=payload.theme,
        locale=payload.locale,
        updated_at=datetime.now(UTC),
    ).on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            "audio_pref_lang": payload.audio_pref_lang,
            "subs_pref_lang": payload.subs_pref_lang,
            "quality_cap_height": payload.quality_cap_height,
            "autoplay_next_episode": payload.autoplay_next_episode,
            "skip_intro": payload.skip_intro,
            "theme": payload.theme,
            "locale": payload.locale,
            "updated_at": datetime.now(UTC),
        },
    )
    await db.execute(stmt)
    await db.commit()
    return payload
