"""Background catalog refresh worker.

Two entry points:

* ``refresh_due_collections()`` — pure function, easy to test, used by
  the scheduler tick and by the admin "force refresh" endpoint.
* ``main()`` — long-running async loop suitable for a separate process
  (systemd service or Docker container).
"""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db import init as db_init, shutdown as db_shutdown
from streamload.db.models import Collection
from streamload.utils.logger import get_logger

from .collections import COLLECTION_DEFS, CollectionDef
from .ingest import ingest_collection
from .tmdb import TmdbClient

log = get_logger(__name__)

POLL_INTERVAL_SECONDS = 600  # 10 minutes


async def refresh_due_collections(
    db: AsyncSession,
    *,
    tmdb_client: Any,
    collection_defs: Optional[list[CollectionDef]] = None,
) -> list[str]:
    """Refresh collections whose last_refreshed_at is older than their TTL."""
    defs = collection_defs if collection_defs is not None else COLLECTION_DEFS
    now = datetime.now(UTC)
    refreshed: list[str] = []
    for d in defs:
        existing = (await db.execute(
            select(Collection).where(Collection.id == d.id)
        )).scalar_one_or_none()
        if existing is not None and existing.last_refreshed_at is not None:
            age = now - existing.last_refreshed_at
            if age < timedelta(hours=d.refresh_ttl_hours):
                log.debug("Collection %s is fresh (age=%s)", d.id, age)
                continue
        log.info("Refreshing collection %s", d.id)
        items = await d.fetch(tmdb_client)
        await ingest_collection(
            db, collection_id=d.id, collection_title=d.title,
            media_type=d.media_type, sort_order=d.sort_order,
            refresh_ttl_hours=d.refresh_ttl_hours,
            items=items,
        )
        refreshed.append(d.id)
    return refreshed


async def main() -> None:
    """Long-running refresh loop. Used as a separate process."""
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload",
    )
    api_key = os.environ.get("TMDB_API_KEY", "")
    db_init(db_url)
    try:
        while True:
            try:
                from streamload.db.session import _session_factory
                async with _session_factory() as session:
                    async with httpx.AsyncClient(timeout=15) as http:
                        tmdb = TmdbClient(api_key=api_key, http=http)
                        refreshed = await refresh_due_collections(
                            session, tmdb_client=tmdb,
                        )
                        if refreshed:
                            log.info("Refreshed: %s", ", ".join(refreshed))
            except Exception:
                log.error("Refresh tick failed", exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    finally:
        await db_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
