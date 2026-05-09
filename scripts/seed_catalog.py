"""Seed the catalog by running collection refreshes directly (no API auth).

Used in dev to populate the catalog without going through HTTP. The
production path is the admin endpoint or the background worker.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Allow running from repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx

from streamload.catalog.collections import COLLECTION_DEFS, get_collection_def
from streamload.catalog.ingest import ingest_collection
from streamload.catalog.tmdb import TmdbClient
from streamload.db import init as db_init, shutdown as db_shutdown
from streamload.services import ServiceRegistry, load_services
from streamload.utils.http import HttpClient


async def refresh_one(collection_id: str) -> None:
    cdef = get_collection_def(collection_id)
    if cdef is None:
        print(f"unknown collection: {collection_id}")
        return
    api_key = os.environ.get("TMDB_API_KEY", "")
    if not api_key:
        print("TMDB_API_KEY missing; aborting")
        return

    print(f"=== Refreshing {collection_id} ===")
    async with httpx.AsyncClient(timeout=20) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        items = await cdef.fetch(tmdb)
        print(f"  TMDB returned {len(items)} items")

    services = [cls(HttpClient()) for cls in ServiceRegistry.get_all()]
    print(f"  loaded {len(services)} service plugins")

    from streamload.db.session import _session_factory
    async with _session_factory() as db:
        await ingest_collection(
            db,
            collection_id=cdef.id,
            collection_title=cdef.title,
            media_type=cdef.media_type,
            sort_order=cdef.sort_order,
            refresh_ttl_hours=cdef.refresh_ttl_hours,
            items=items,
            services=services,
        )
    print(f"  ingest done for {collection_id}")


async def main(*collection_ids: str) -> None:
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload",
    )
    db_init(db_url)
    load_services()

    targets = list(collection_ids) if collection_ids else [d.id for d in COLLECTION_DEFS]
    try:
        for cid in targets:
            try:
                await refresh_one(cid)
            except Exception as exc:
                print(f"  ERROR for {cid}: {type(exc).__name__}: {exc}")
                import traceback; traceback.print_exc()
    finally:
        await db_shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(main(*sys.argv[1:]))
