"""Live search endpoint — queries TMDB and returns typed results."""
from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel

from streamload.api.deps import CurrentUser
from streamload.catalog.tmdb import TmdbClient

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
    q: str = Query(min_length=1, max_length=100),
) -> SearchResponse:
    async with httpx.AsyncClient(timeout=15) as http:
        client = _build_tmdb_client(http)
        items = await client.search_multi(q)
    return SearchResponse(
        query=q,
        results=[
            SearchResult(
                tmdb_id=i.tmdb_id, media_type=i.media_type,
                title=i.title, year=i.year, poster_url=i.poster_url,
            ) for i in items
        ],
    )
