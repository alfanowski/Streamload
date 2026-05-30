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


class SearchPerson(BaseModel):
    tmdb_id: int
    name: str
    profile_url: str | None
    department: str | None
    known_for: list[str]


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    people: list[SearchPerson]
    # When the query was typo-corrected (e.g. "frinds" → "Friends"), the term
    # actually searched. Null when the original query matched directly.
    corrected: str | None = None


def _build_tmdb_client(http: httpx.AsyncClient) -> TmdbClient:
    api_key = os.environ.get("TMDB_API_KEY", "")
    return TmdbClient(api_key=api_key, http=http)


@router.get("", response_model=SearchResponse)
async def search(
    user: CurrentUser,
    db: SessionDep,
    request: Request,
    q: str = Query(min_length=1, max_length=100),
    page: int = Query(default=1, ge=1, le=5),
) -> SearchResponse:
    qh = hashlib.sha256(q.encode("utf-8")).hexdigest()

    # Bookkeeping FIRST so it lands even if TMDB call fails. We only log
    # the first page to avoid double-counting an infinite-scroll session.
    if page == 1:
        db.add(SearchHistory(user_id=user.id, query_text=q, query_hash=qh))
    result_count = 0
    items = []
    people = []
    corrected = None
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            client = _build_tmdb_client(http)
            # Page 1 runs the full user-proof pipeline (plain → title+actor
            # split → typo correction); later pages just paginate the plain
            # match (the fallbacks have no meaningful pagination).
            if page == 1:
                bundle = await client.smart_search(q, page=page)
            else:
                bundle = await client.search_multi_all(q, page=page)
        items = bundle["titles"]
        people = bundle["people"]
        corrected = bundle.get("corrected")
        result_count = len(items) + len(people)
    except Exception:
        items = []
        people = []
        log.warning("TMDB search failed for %r (page=%d)", q, page, exc_info=True)
    finally:
        if page == 1:
            await emit_event(db, request, user_id=user.id, event_type="search.run",
                             payload={"query_hash": qh, "result_count": result_count})
            await db.commit()

    return SearchResponse(
        query=q,
        corrected=corrected,
        results=[
            SearchResult(
                tmdb_id=i.tmdb_id, media_type=i.media_type,
                title=i.title, year=i.year, poster_url=i.poster_url,
            ) for i in items
        ],
        people=[
            SearchPerson(
                tmdb_id=p.tmdb_id, name=p.name, profile_url=p.profile_url,
                department=p.known_for_department, known_for=p.known_for_titles,
            ) for p in people
        ],
    )
