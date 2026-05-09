"""Server-side telemetry helper.

Routes call `await emit(db, request, user_id, event_type, payload)` after a
successful mutation. The same closed enum as /events validates type names.

This is for server-driven events (auth/favorites/watchlist mutations);
client-driven events (catalog.view, play.start/complete, app.start) come in
via POST /api/events instead.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db.models import Event


async def emit(
    db: AsyncSession,
    request: Request,
    *,
    user_id: Optional[uuid.UUID],
    event_type: str,
    payload: Optional[dict] = None,
) -> None:
    """Insert one event. Caller commits as part of the surrounding transaction."""
    db.add(Event(
        user_id=user_id,
        event_type=event_type,
        payload=payload or {},
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        app_version=None,  # only populated for client-posted events
        occurred_at=datetime.now(UTC),
    ))
