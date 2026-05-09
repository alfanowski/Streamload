"""Skip intro / outro marker endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import IntroMarker

router = APIRouter(prefix="/intro", tags=["intro"])


class IntroResponse(BaseModel):
    intro_start: int
    intro_end: int
    outro_start: int | None = None
    confidence: float | None = None


@router.get("/{tmdb_id}/s{season}", response_model=IntroResponse | None)
async def get_intro(
    tmdb_id: int,
    season: int,
    user: CurrentUser,
    db: SessionDep,
    response: Response,
) -> IntroResponse | None:
    row = (await db.execute(
        select(IntroMarker)
        .where(IntroMarker.tmdb_id == tmdb_id)
        .where(IntroMarker.season_number == season)
    )).scalar_one_or_none()
    if row is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return IntroResponse(
        intro_start=row.intro_start_seconds,
        intro_end=row.intro_end_seconds,
        outro_start=row.outro_start_seconds,
        confidence=float(row.confidence) if row.confidence is not None else None,
    )
