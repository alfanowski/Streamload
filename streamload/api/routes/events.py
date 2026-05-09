"""Telemetry ingestion: client posts batched events captured per spec §5.4."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import Event

router = APIRouter(tags=["events"])

# Closed enum from spec §5.4. Anything outside this list is rejected at
# validation time so we never accumulate garbage event types in analytics.
ALLOWED_EVENT_TYPES = {
    "auth.login_success",
    "auth.login_failed",
    "auth.logout",
    "auth.passkey_register",
    "catalog.view",
    "search.run",
    "play.start",
    "play.complete",
    "favorite.add",
    "favorite.remove",
    "watchlist.add",
    "watchlist.remove",
    "app.start",
    "plugin_pack.installed",
    "plugin_pack.updated",
}


class EventIn(BaseModel):
    event_type: str
    payload: dict = Field(default_factory=dict)


class BatchIn(BaseModel):
    app_version: str | None = None
    events: Annotated[list[EventIn], Field(min_length=0, max_length=100)]


@router.post("/events", status_code=202)
async def post_events(
    payload: BatchIn,
    user: CurrentUser,
    db: SessionDep,
    request: Request,
) -> dict[str, int]:
    # Validate event types up front; reject the whole batch on any unknown.
    for ev in payload.events:
        if ev.event_type not in ALLOWED_EVENT_TYPES:
            from fastapi import HTTPException, status as http_status
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"unknown event_type {ev.event_type!r}",
            )

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    now = datetime.now(UTC)

    for ev in payload.events:
        db.add(Event(
            user_id=user.id,
            event_type=ev.event_type,
            payload=ev.payload,
            ip=ip,
            user_agent=user_agent,
            app_version=payload.app_version,
            occurred_at=now,
        ))
    await db.commit()
    return {"accepted": len(payload.events)}
