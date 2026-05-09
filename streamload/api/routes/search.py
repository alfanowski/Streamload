"""Live search endpoint — queries TMDB and returns typed results."""
from __future__ import annotations

import hashlib
import os

import httpx
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from streamload.api.deps import CurrentUser, SessionDep
from streamload.api.telemetry import emit as emit_event
from streamload.catalog.tmdb import TmdbClient
from streamload.db.models import SearchHistory
from streamload.utils.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


class SearchResult(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    year: int | None
    poster_url: str | None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


def _build_tmdb_client(http: httpx.AsyncClient) -> TmdbClient:
    api_key = os.environ.get("TMDB_API_KEY", "")
    return TmdbClient(api_key=api_key, http=http)


@router.get("", response_model=SearchResponse)
async def search(
    user: CurrentUser,
    db: SessionDep,
    request: Request,
    q: str = Query(min_length=1, max_length=100),
) -> SearchResponse:
    qh = hashlib.sha256(q.encode("utf-8")).hexdigest()

    # Bookkeeping FIRST so it lands even if TMDB call fails.
    db.add(SearchHistory(user_id=user.id, query_text=q, query_hash=qh))
    result_count = 0
    items = []
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            client = _build_tmdb_client(http)
            items = await client.search_multi(q)
        result_count = len(items)
    except Exception:
        items = []
        log.warning("TMDB search failed for %r", q, exc_info=True)
    finally:
        await emit_event(db, request, user_id=user.id, event_type="search.run",
                         payload={"query_hash": qh, "result_count": result_count})
        await db.commit()

    return SearchResponse(
        query=q,
        results=[
            SearchResult(
                tmdb_id=i.tmdb_id, media_type=i.media_type,
                title=i.title, year=i.year, poster_url=i.poster_url,
            ) for i in items
        ],
    )
