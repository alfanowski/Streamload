"""Catalog detail endpoint.

v3: pure metadata mirror. Lazy-ingest pulls from TMDB when the title isn't
yet cached; sources are never resolved server-side and are always returned
as an empty list. The client resolves sources locally via its plugin runtime.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from streamload.api.deps import CurrentUser, SessionDep
from streamload.catalog.ingest import ingest_single_title
from streamload.catalog.playability import rank_by_playability
from streamload.catalog.service import CatalogService
from streamload.catalog.tmdb import TmdbClient, TmdbItem, _is_real_title, _parse_year
from streamload.utils.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/catalog", tags=["catalog"])
# Person bio + filmography proxy lives alongside catalog (same TmdbClient,
# same auth dep) but under its own `/person` prefix so the URLs read
# naturally — `/api/person/287` for the PersonPage, `/api/person/287/credits`
# for the filmography row.
person_router = APIRouter(prefix="/person", tags=["person"])


class SourceResponse(BaseModel):
    label: str
    score: float


class CatalogItemResponse(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    original_title: str | None
    year: int | None
    poster_url: str | None
    backdrop_url: str | None
    overview: str | None
    rating: float | None
    runtime_minutes: int | None
    seasons_count: int | None
    genres: list[str]
    sources: list[SourceResponse]   # always [] in v3 server response


async def _fetch_tmdb_item(
    client: TmdbClient, tmdb_id: int, media_type: Optional[str],
) -> Optional[TmdbItem]:
    order = ["movie", "tv"] if media_type != "tv" else ["tv", "movie"]
    for mt in order:
        try:
            return await client.get_movie(tmdb_id) if mt == "movie" else await client.get_tv(tmdb_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                log.warning("TMDB %s/%s error: %s", mt, tmdb_id, e)
            continue
        except Exception:
            log.warning("TMDB lookup failed for %s/%s", mt, tmdb_id, exc_info=True)
            continue
    return None


class VideoResponse(BaseModel):
    """Subset of TMDB ``/videos`` results — only fields the client uses."""
    key: str          # YouTube video id
    site: str         # always "YouTube" (filtered)
    type: str         # "Trailer" / "Teaser" / "Clip" / ...
    official: bool
    name: str | None = None


class LogoResponse(BaseModel):
    """The title's official logo (typographic wordmark), or null."""
    logo_url: str | None = None


class CreditPersonResponse(BaseModel):
    """Subset of TMDB credit-person fields used by the title page sidebar."""
    id: int
    name: str
    character: str | None = None  # cast only
    job: str | None = None        # crew only
    profile_url: str | None = None
    order: int | None = None      # cast ordering (lower = bigger role)


class CreditsResponse(BaseModel):
    cast: list[CreditPersonResponse]
    crew: list[CreditPersonResponse]


# Crew jobs we surface in the "CREATO DA" block. Anything else gets
# dropped so the title page sidebar stays terse and signal-rich. Keep
# this list small — adding 20 producers per title flips the section into
# a wall of names that nobody will read.
_CREW_JOBS = {"Creator", "Director", "Showrunner", "Producer", "Writer"}


@router.get("/{tmdb_id}/credits", response_model=CreditsResponse)
async def get_item_credits(
    tmdb_id: int,
    user: CurrentUser,
    media_type: str,
) -> CreditsResponse:
    """Proxy TMDB ``/{movie|tv}/{id}/credits`` for the title page sidebar.

    Caps cast at 10 (by TMDB's ``order`` field — main cast first), and
    filters crew to a curated job allow-list so the sidebar stays terse.
    """
    if media_type not in ("movie", "tv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "media_type must be 'movie' or 'tv'")
    api_key = os.environ.get("TMDB_API_KEY", "")
    if not api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "TMDB not configured")
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        try:
            data = await tmdb.get_credits(tmdb_id, media_type=media_type)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return CreditsResponse(cast=[], crew=[])
            log.warning("TMDB credits %s/%s error: %s", media_type, tmdb_id, e)
            return CreditsResponse(cast=[], crew=[])

        raw_cast = list(data.get("cast", []))
        # TMDB returns cast sorted by `order` ascending (main cast first),
        # but the field is occasionally missing — fall back to insertion
        # order in that case.
        raw_cast.sort(key=lambda p: p.get("order") if p.get("order") is not None else 9999)
        cast = [
            CreditPersonResponse(
                id=int(p.get("id") or 0),
                name=str(p.get("name") or ""),
                character=p.get("character"),
                profile_url=tmdb.image_url(p.get("profile_path"), size="w185"),
                order=p.get("order"),
            )
            for p in raw_cast[:10]
            if p.get("name")
        ]

        raw_crew = list(data.get("crew", []))
        seen_ids: set[tuple[int, str]] = set()
        crew: list[CreditPersonResponse] = []
        for p in raw_crew:
            job = str(p.get("job") or "")
            if job not in _CREW_JOBS:
                continue
            person_id = int(p.get("id") or 0)
            key = (person_id, job)
            if key in seen_ids:
                continue
            seen_ids.add(key)
            crew.append(
                CreditPersonResponse(
                    id=person_id,
                    name=str(p.get("name") or ""),
                    job=job,
                    profile_url=tmdb.image_url(p.get("profile_path"), size="w185"),
                )
            )
            # Hard cap to keep the sidebar visually tight.
            if len(crew) >= 6:
                break
    return CreditsResponse(cast=cast, crew=crew)


@router.get("/{tmdb_id}/videos", response_model=list[VideoResponse])
async def get_item_videos(
    tmdb_id: int,
    user: CurrentUser,
    media_type: str,
) -> list[VideoResponse]:
    """Proxy TMDB ``/{movie|tv}/{id}/videos``, returning YouTube items only.

    The client's HeroTrailer feeds the first matching key into a YouTube
    IFrame Player. We keep TMDB credentials server-side; the client never
    sees the API key.
    """
    if media_type not in ("movie", "tv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "media_type must be 'movie' or 'tv'")
    api_key = os.environ.get("TMDB_API_KEY", "")
    if not api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "TMDB not configured")
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        try:
            results = await tmdb.get_videos(tmdb_id, media_type=media_type)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            log.warning("TMDB videos %s/%s error: %s", media_type, tmdb_id, e)
            return []
    return [
        VideoResponse(
            key=str(v.get("key") or ""),
            site=str(v.get("site") or ""),
            type=str(v.get("type") or ""),
            official=bool(v.get("official", False)),
            name=v.get("name"),
        )
        for v in results
        if v.get("site") == "YouTube" and v.get("key")
    ]


@router.get("/{tmdb_id}/logo", response_model=LogoResponse)
async def get_item_logo(
    tmdb_id: int,
    user: CurrentUser,
    media_type: str,
) -> LogoResponse:
    """Best official title-logo (transparent PNG) for a movie/tv, or null.

    The home hero renders this wordmark instead of app-typeset text when it
    exists, falling back to text otherwise. Never throws on missing art — a
    null ``logo_url`` simply means "use the text fallback".
    """
    if media_type not in ("movie", "tv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "media_type must be 'movie' or 'tv'")
    api_key = os.environ.get("TMDB_API_KEY", "")
    if not api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "TMDB not configured")
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        try:
            url = await tmdb.get_logo_url(tmdb_id, media_type=media_type)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return LogoResponse(logo_url=None)
            log.warning("TMDB logo %s/%s error: %s", media_type, tmdb_id, e)
            return LogoResponse(logo_url=None)
    return LogoResponse(logo_url=url)


# ──────────────────────────────────────────────────────────────────────────
# Home "rows" — thin TMDB proxies returning MediaSummary-shaped JSON.
# Used by the client's PosterRow / BackdropRow components. Each row endpoint
# is independent so a slow / failing row doesn't block the whole page.
#
# Caller picks the row length via the ``limit`` query param (default 60,
# capped at 100 — TMDB returns 20 per page, so >20 means we fetch multiple
# pages and concat). The ``page`` param lets a future "Vedi tutti" grid
# paginate beyond the first slice.
# ──────────────────────────────────────────────────────────────────────────

# Default row length — bumped across two passes per operator: May 16
# 20→40, May 17 40→60. The bigger jump is for "always same ugly titles"
# (P6): at 40 the horizontal scroll still felt thin compared to Netflix
# rows; 60 = 3 TMDB pages, ~3 full viewport widths of scrollable
# content per row.
_ROW_DEFAULT_LIMIT = 60
# Hard ceiling so a buggy / malicious caller can't force us to fan out
# 50 TMDB requests per row.
_ROW_MAX_LIMIT = 100
# TMDB page size — every TMDB list endpoint returns at most 20 items per
# page. We use this constant to derive how many pages to fetch when a
# caller asks for more than 20 items in one row.
_TMDB_PAGE_SIZE = 20


def _normalize_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > _ROW_MAX_LIMIT:
        return _ROW_MAX_LIMIT
    return limit


async def _collect_pages(
    fetch_page,  # async (page: int) -> list[TmdbItem]
    *,
    limit: int,
    start_page: int,
) -> list[TmdbItem]:
    """Fetch enough TMDB pages to satisfy ``limit`` items, starting from
    ``start_page``. Stops early when a page returns fewer than
    ``_TMDB_PAGE_SIZE`` items (= we've hit the end of the result set)."""
    out: list[TmdbItem] = []
    page = start_page
    while len(out) < limit:
        try:
            chunk = await fetch_page(page)
        except httpx.HTTPError as exc:
            # TMDB unreachable / timed out / transient network blip. Degrade
            # gracefully: return whatever we've gathered so far (empty → the
            # client just renders no row) instead of 500-ing the whole screen.
            log.warning("TMDB page fetch failed (page=%s): %r — serving %d cached/partial items", page, exc, len(out))
            break
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < _TMDB_PAGE_SIZE:
            break
        page += 1
    return out[:limit]


class MediaSummaryResponse(BaseModel):
    """Mirrors ``streamload_client.MediaSummary`` 1:1.

    Kept inline here (rather than imported from a shared schema) because
    catalog rows are the only producer and the client model is the only
    consumer — a shared module would add ceremony for one type.
    """
    tmdb_id: int
    media_type: str
    title: str
    year: int | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None


def _to_summary(item: TmdbItem) -> MediaSummaryResponse:
    return MediaSummaryResponse(
        tmdb_id=item.tmdb_id,
        media_type=item.media_type,
        title=item.title,
        year=item.year,
        poster_url=item.poster_url,
        backdrop_url=item.backdrop_url,
    )


# TMDB TV genre IDs the platform never wants: Talk (10767) and News (10763).
# These get mis-classified as "serie tv" and pollute filmographies and rows.
_EXCLUDED_TV_GENRES = {10767, 10763}


def _require_tmdb_key() -> str:
    api_key = os.environ.get("TMDB_API_KEY", "")
    if not api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "TMDB not configured")
    return api_key


# TMDB biographies are community-contributed and frequently pasted from
# Wikipedia, which leaves a CC-BY-SA attribution footer baked into the text
# (in several languages). It's boilerplate the user should never see, so we
# cut the bio at the first attribution marker.
_WIKI_ATTRIBUTION_MARKERS = (
    "Description above from the Wikipedia",
    "La descrizione qui sopra deriva",
    "from the Wikipedia article",
    "Questo testo proviene dall'articolo di Wikipedia",
    "Diese Beschreibung stammt aus dem Wikipedia",
    "La description ci-dessus provient de l",
)


def _strip_wiki_attribution(bio: str) -> str:
    cut = len(bio)
    for marker in _WIKI_ATTRIBUTION_MARKERS:
        idx = bio.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    return bio[:cut].strip()


# Character strings that mark a NON-acting appearance (the person playing
# themselves on a talk show, in a concert film, a documentary, etc.).
_SELF_MARKERS = {
    "self", "himself", "herself", "themselves", "host", "presenter",
    "se stesso", "se stessa", "presentatore", "presentatrice", "narrator",
    "narratore",
}


def _derive_department(credits: dict, fallback: str | None) -> str | None:
    """Work out a person's REAL profession from their filmography.

    TMDB's ``known_for_department`` mislabels musicians / personalities as
    "Acting" the moment they appear as themselves once. We instead count their
    actual work: real acting roles (a character that isn't "Self") vs. crew
    departments. If neither dominates — i.e. they're mostly playing themselves —
    we return None rather than claim a profession we can't stand behind.
    """
    cast = credits.get("cast") or []
    crew = credits.get("crew") or []
    real_acting = 0
    self_appearances = 0
    for c in cast:
        if c.get("media_type") not in ("movie", "tv"):
            continue
        character = (c.get("character") or "").strip().lower()
        words = set(character.replace("(", " ").replace(")", " ").split())
        if not character or character in _SELF_MARKERS or words & _SELF_MARKERS:
            self_appearances += 1
        else:
            real_acting += 1

    crew_counts: dict[str, int] = {}
    for cw in crew:
        if cw.get("media_type") not in ("movie", "tv"):
            continue
        dept = cw.get("department")
        if dept:
            crew_counts[dept] = crew_counts.get(dept, 0) + 1
    top_crew, top_n = None, 0
    for dept, n in crew_counts.items():
        if n > top_n:
            top_crew, top_n = dept, n

    # A clearly-dominant crew role wins (a director who barely acts).
    if top_n > real_acting and top_n >= 2:
        return top_crew
    # A real body of acting work that isn't drowned out by Self appearances.
    if real_acting >= 2 and real_acting >= self_appearances:
        return "Acting"
    # Inconclusive — mostly Self / too thin. Keep a strong non-Acting TMDB
    # hint, but never assert "Acting" for someone who barely acts.
    if fallback and fallback != "Acting":
        return fallback
    return None


def _best_biography(data: dict) -> str | None:
    """Pick + clean the best available biography for a person.

    The text comes from the TMDB API (``/person/{id}``), localised to it-IT.
    When the Italian bio is empty we fall back to the appended ``translations``
    payload — but ONLY to Italian or English (an "any language" fallback
    surfaced surreal Russian/Korean bios). The chosen bio is then stripped of
    the Wikipedia CC-BY-SA attribution footer TMDB bakes into community text.
    """
    candidate = (data.get("biography") or "").strip()
    if not candidate:
        translations = (data.get("translations") or {}).get("translations") or []
        by_lang: dict[str, str] = {}
        for t in translations:
            lang = t.get("iso_639_1")
            bio = ((t.get("data") or {}).get("biography") or "").strip()
            if lang and bio and lang not in by_lang:
                by_lang[lang] = bio
        for lang in ("it", "en"):
            if by_lang.get(lang):
                candidate = by_lang[lang]
                break
    candidate = _strip_wiki_attribution(candidate)
    return candidate or None


def _validate_media_type(value: str, *, allow_all: bool = False) -> str:
    allowed = {"movie", "tv"} | ({"all"} if allow_all else set())
    if value not in allowed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"media_type must be one of {sorted(allowed)}",
        )
    return value


@router.get("/rows/trending", response_model=list[MediaSummaryResponse])
async def rows_trending(
    user: CurrentUser,
    period: str = "week",
    media_type: str = "all",
    limit: int = _ROW_DEFAULT_LIMIT,
    page: int = 1,
) -> list[MediaSummaryResponse]:
    """``period`` is ``day`` or ``week``; ``media_type`` is ``all``/``movie``/``tv``.

    ``limit`` and ``page`` let the client request longer rows or paginate
    beyond the first slice. Default 40 items, hard-capped at 100.
    """
    if period not in ("day", "week"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "period must be 'day' or 'week'")
    _validate_media_type(media_type, allow_all=True)
    limit = _normalize_limit(limit)
    if page < 1:
        page = 1
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        fn = tmdb.trending_day if period == "day" else tmdb.trending_week
        items = await _collect_pages(
            lambda p: fn(media_type=media_type, page=p),
            limit=limit,
            start_page=page,
        )
    items = rank_by_playability(items)
    return [_to_summary(i) for i in items]


@router.get("/rows/new-releases", response_model=list[MediaSummaryResponse])
async def rows_new_releases(
    user: CurrentUser,
    media_type: str,
    limit: int = _ROW_DEFAULT_LIMIT,
    page: int = 1,
) -> list[MediaSummaryResponse]:
    _validate_media_type(media_type)
    limit = _normalize_limit(limit)
    if page < 1:
        page = 1
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        items = await _collect_pages(
            lambda p: tmdb.new_releases(media_type=media_type, page=p),
            limit=limit,
            start_page=page,
        )
    items = rank_by_playability(items)
    return [_to_summary(i) for i in items]


@router.get("/rows/by-genre", response_model=list[MediaSummaryResponse])
async def rows_by_genre(
    user: CurrentUser,
    genre_ids: str,
    media_type: str,
    original_language: str | None = None,
    origin: str = "western",
    limit: int = _ROW_DEFAULT_LIMIT,
    page: int = 1,
) -> list[MediaSummaryResponse]:
    """``genre_ids`` is a comma-separated list of TMDB genre IDs (e.g. ``80,53``).

    ``origin`` is ``western`` (default) or ``jp``; the Anime rows pass ``jp``
    so they surface Japanese anime instead of Western cartoons.
    """
    _validate_media_type(media_type)
    try:
        ids = [int(g) for g in genre_ids.split(",") if g.strip()]
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "genre_ids must be a comma-separated list of integers",
        )
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "genre_ids required")
    limit = _normalize_limit(limit)
    if page < 1:
        page = 1
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        items = await _collect_pages(
            lambda p: tmdb.discover_by_genre(
                genre_ids=ids,
                media_type=media_type,
                original_language=original_language,
                origin=origin,
                page=p,
            ),
            limit=limit,
            start_page=page,
        )
    items = rank_by_playability(items, is_anime_row=(origin == "jp"))
    return [_to_summary(i) for i in items]


@router.get("/rows/top-rated", response_model=list[MediaSummaryResponse])
async def rows_top_rated(
    user: CurrentUser,
    media_type: str,
    limit: int = _ROW_DEFAULT_LIMIT,
    page: int = 1,
) -> list[MediaSummaryResponse]:
    _validate_media_type(media_type)
    limit = _normalize_limit(limit)
    if page < 1:
        page = 1
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        fn = tmdb.top_rated_movies if media_type == "movie" else tmdb.top_rated_tv
        items = await _collect_pages(
            lambda p: fn(page=p),
            limit=limit,
            start_page=page,
        )
    items = rank_by_playability(items)
    return [_to_summary(i) for i in items]


@router.get("/{tmdb_id}/similar", response_model=list[MediaSummaryResponse])
async def get_item_similar(
    tmdb_id: int,
    user: CurrentUser,
    media_type: str,
    limit: int = _ROW_DEFAULT_LIMIT,
) -> list[MediaSummaryResponse]:
    _validate_media_type(media_type)
    limit = _normalize_limit(limit)
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        try:
            items = await tmdb.similar(tmdb_id, media_type=media_type)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            log.warning("TMDB similar %s/%s error: %s", media_type, tmdb_id, e)
            return []
    return [_to_summary(i) for i in items[:limit]]


@router.get("/{tmdb_id}/recommendations", response_model=list[MediaSummaryResponse])
async def get_item_recommendations(
    tmdb_id: int,
    user: CurrentUser,
    media_type: str,
    limit: int = _ROW_DEFAULT_LIMIT,
) -> list[MediaSummaryResponse]:
    _validate_media_type(media_type)
    limit = _normalize_limit(limit)
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        try:
            items = await tmdb.recommendations(tmdb_id, media_type=media_type)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            log.warning(
                "TMDB recommendations %s/%s error: %s",
                media_type,
                tmdb_id,
                e,
            )
            return []
    return [_to_summary(i) for i in items[:limit]]


@router.get("/{tmdb_id}", response_model=CatalogItemResponse)
async def get_item(
    tmdb_id: int,
    db: SessionDep,
    user: CurrentUser,
    media_type: Optional[str] = None,
) -> CatalogItemResponse:
    svc = CatalogService(db)
    item = await svc.get_item(tmdb_id, media_type=media_type)

    if item is None:
        api_key = os.environ.get("TMDB_API_KEY", "")
        if not api_key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "title not found in catalog")
        async with httpx.AsyncClient(timeout=15) as http:
            tmdb = TmdbClient(api_key=api_key, http=http)
            tmdb_item = await _fetch_tmdb_item(tmdb, tmdb_id, media_type)
            if tmdb_item is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "title not found on TMDB")
            await ingest_single_title(db, item=tmdb_item, tmdb=tmdb)
        item = await svc.get_item(tmdb_id, media_type=tmdb_item.media_type)
        if item is None:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "ingest failed")

    return CatalogItemResponse(
        tmdb_id=item.tmdb_id,
        media_type=item.media_type,
        title=item.title,
        original_title=item.original_title,
        year=item.year,
        poster_url=item.poster_url,
        backdrop_url=item.backdrop_url,
        overview=item.overview,
        rating=float(item.rating) if item.rating is not None else None,
        runtime_minutes=item.runtime_minutes,
        seasons_count=item.seasons_count,
        genres=item.genres,
        sources=[],
    )


# ──────────────────────────────────────────────────────────────────────────
# Person endpoints (Pass 3 CAST-1) — bio + combined filmography. Cast cards
# on the title page link here; the page renders an editorial hero plus a
# popularity-sorted PosterRow of every movie / tv the person appeared in
# (or directed).
# ──────────────────────────────────────────────────────────────────────────


class PersonResponse(BaseModel):
    tmdb_id: int
    name: str
    biography: str | None = None
    birthday: str | None = None     # ISO date "YYYY-MM-DD"
    deathday: str | None = None     # ISO date or null
    place_of_birth: str | None = None
    profile_url: str | None = None  # w500 — used in the editorial hero
    also_known_as: list[str] = []
    known_for_department: str | None = None


class PersonCreditItemResponse(BaseModel):
    """MediaSummary-shaped entry for the Filmografia row. Mirrors
    ``MediaSummaryResponse`` above but adds ``character`` so the row can
    show "as Daniel Plainview" under each title if we ever want it."""
    tmdb_id: int
    media_type: str
    title: str
    year: int | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    character: str | None = None


@person_router.get("/{person_id}", response_model=PersonResponse)
async def get_person(
    person_id: int,
    user: CurrentUser,
) -> PersonResponse:
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        try:
            data = await tmdb.get_person(person_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, "person not found on TMDB",
                )
            log.warning("TMDB person %s error: %s", person_id, e)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "TMDB upstream error",
            )
        return PersonResponse(
            tmdb_id=int(data.get("id") or person_id),
            name=str(data.get("name") or ""),
            biography=_best_biography(data),
            birthday=data.get("birthday"),
            deathday=data.get("deathday"),
            place_of_birth=data.get("place_of_birth"),
            # w500 = editorial hero size. Same TMDB CDN, just a bigger
            # variant than the w185 thumbnails the CastCard uses.
            profile_url=tmdb.image_url(data.get("profile_path"), size="w500"),
            also_known_as=list(data.get("also_known_as") or []),
            # Derived from the actual filmography (combined_credits, bundled via
            # append_to_response) — TMDB's raw known_for_department mislabels
            # musicians/personalities as "Acting".
            known_for_department=_derive_department(
                data.get("combined_credits") or {},
                data.get("known_for_department"),
            ),
        )


@person_router.get(
    "/{person_id}/credits", response_model=list[PersonCreditItemResponse],
)
async def get_person_credits(
    person_id: int,
    user: CurrentUser,
) -> list[PersonCreditItemResponse]:
    """Combined movies + tv where the person was cast or crewed.

    TMDB returns separate ``cast`` and ``crew`` arrays — we union them,
    dedupe by ``(tmdb_id, media_type)`` (preferring the cast entry so
    we keep the character name), apply the same poster + title quality
    filter the row endpoints use (drops fresh-upload spam), and sort
    desc by popularity so the most recognisable titles surface first.
    """
    api_key = _require_tmdb_key()
    async with httpx.AsyncClient(timeout=15) as http:
        tmdb = TmdbClient(api_key=api_key, http=http)
        try:
            data = await tmdb.get_person_credits(person_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            log.warning(
                "TMDB person credits %s error: %s", person_id, e,
            )
            return []

    # Cast entries win the dedup: they carry the `character` field.
    raw_cast = list(data.get("cast", []))
    raw_crew = list(data.get("crew", []))
    by_key: dict[tuple[int, str], dict] = {}
    for entry in raw_cast:
        key = (int(entry.get("id") or 0), str(entry.get("media_type") or ""))
        if key[0] and key[1] and key not in by_key:
            by_key[key] = {"raw": entry, "from_cast": True}
    for entry in raw_crew:
        key = (int(entry.get("id") or 0), str(entry.get("media_type") or ""))
        if key[0] and key[1] and key not in by_key:
            by_key[key] = {"raw": entry, "from_cast": False}

    items: list[tuple[float, PersonCreditItemResponse]] = []
    for (tmdb_id, media_type), bundle in by_key.items():
        raw = bundle["raw"]
        if media_type not in ("movie", "tv"):
            continue
        # Drop talk shows / news — they're not real filmography (and the
        # platform doesn't want them at all). TMDB tags them with these genres.
        if media_type == "tv" and (
            set(raw.get("genre_ids") or []) & _EXCLUDED_TV_GENRES
        ):
            continue
        # TV uses `name` + `first_air_date`; movies use `title` + `release_date`.
        title = (raw.get("title") if media_type == "movie" else raw.get("name")) or ""
        date_str = (
            raw.get("release_date") if media_type == "movie"
            else raw.get("first_air_date")
        )
        poster_url = tmdb.image_url(raw.get("poster_path"))
        backdrop_url = tmdb.image_url(raw.get("backdrop_path"), size="w1280")
        # Same quality bar as catalog rows — no posterless items, no
        # emoji/digit spam titles. Actors' filmographies have lots of
        # community uploads that don't pass these checks.
        if not poster_url or not _is_real_title(title):
            continue
        item = PersonCreditItemResponse(
            tmdb_id=tmdb_id,
            media_type=media_type,
            title=title,
            year=_parse_year(date_str),
            poster_url=poster_url,
            backdrop_url=backdrop_url,
            character=raw.get("character") if bundle["from_cast"] else None,
        )
        # Base quality: rating (gated on vote_count) blended with popularity.
        rating = float(raw.get("vote_average") or 0.0)
        votes = int(raw.get("vote_count") or 0)
        popularity = float(raw.get("popularity") or 0.0)
        rating_score = rating if votes >= 50 else rating * (votes / 50.0)
        pop_norm = min(popularity / 20.0, 10.0)
        quality = rating_score * 0.7 + pop_norm * 0.3

        # Role PROMINENCE — lead roles must rank above bit parts. A person's
        # billing `order` (0 = top-billed) drives this; crew credits (no order)
        # sit mid-pack. A TV guest with a handful of episodes (e.g. Brad Pitt's
        # one Friends appearance) is heavily demoted so cameos don't outrank the
        # films they actually starred in.
        order = raw.get("order")
        if bundle["from_cast"] and order is not None:
            prominence = max(0.0, 1.0 - int(order) / 12.0)
        else:
            prominence = 0.5
        episode_count = raw.get("episode_count")
        if media_type == "tv" and episode_count is not None and episode_count <= 3:
            prominence *= 0.2

        # Prominence scales quality so a starring role in a good film beats a
        # cameo in a more popular one, while quality still separates the leads.
        score = quality * (0.25 + 0.75 * prominence)
        items.append((score, item))

    items.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in items]
