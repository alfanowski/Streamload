"""Async TMDB v3 client.

Returns typed ``TmdbItem`` dataclasses. Localized to ``it-IT`` by default
(can be overridden per call). Image URLs are pre-built with the default
``w500`` size — caller can switch via ``image_url(path, size=...)``.

Rate limit: TMDB allows 40 req/sec for free tier — way more than we need.
We don't add explicit throttling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from streamload.utils.logger import get_logger

log = get_logger(__name__)

_BASE = "https://api.themoviedb.org/3"
_IMG_BASE = "https://image.tmdb.org/t/p"

# Western catalog — countries our Italian plugins (sc / au / rai) actually
# cover. Used by discover_* + new_releases as `with_origin_country` so the
# Home doesn't surface Korean dramas / Turkish soaps / Indian regional
# titles that the user can't play. Anime is the explicit exception (see
# `discover_anime`, which keeps JP origin).
_WESTERN_COUNTRIES = "US|GB|IT|FR|ES|DE|CA|AU|IE|NL|BE|SE|NO|DK|FI|PT|CH|AT|NZ"

# Minimum TMDB vote_count to surface a title in a row. TMDB indexes every
# upload, including fresh spam ("★1★888★633★4176★ Why") — filtering by
# >=20 votes drops the chaff without losing genuine indie/regional titles.
_VOTE_FLOOR = 20


@dataclass
class TmdbItem:
    tmdb_id: int
    media_type: str  # 'movie' | 'tv'
    title: str
    original_title: Optional[str] = None
    year: Optional[int] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    overview: Optional[str] = None
    rating: Optional[float] = None
    runtime_minutes: Optional[int] = None
    seasons_count: Optional[int] = None
    genres: list[str] = field(default_factory=list)
    # Scorer fields (sub-plan 9 playability ranking) — populated from the raw
    # TMDB payload so the heuristic needs no extra round-trips.
    original_language: Optional[str] = None
    origin_country: list[str] = field(default_factory=list)
    vote_count: int = 0
    popularity: float = 0.0


@dataclass
class TmdbPerson:
    tmdb_id: int
    name: str
    profile_url: Optional[str] = None
    known_for_department: Optional[str] = None
    known_for_titles: list[str] = field(default_factory=list)


# Departments we keep even when known_for is empty. Anyone outside this set
# AND with no notable credits is almost always crew noise (sound assistants,
# caterers) that TMDB indexes but the operator never wants surfaced.
_PEOPLE_DEPARTMENTS = {"Acting", "Directing", "Writing", "Production"}


def _parse_year(date_str: Optional[str]) -> Optional[int]:
    if not date_str or len(date_str) < 4:
        return None
    try:
        return int(date_str[:4])
    except ValueError:
        return None


def _is_real_title(t: Optional[str]) -> bool:
    """Reject titles that are mostly emoji / punctuation / digits.

    Used to drop TMDB spam entries that surface in fresh `discover` queries
    (e.g. "★1★888★633★4176★ Why"). Real titles have ≥3 letters AND letters
    make up ≥30% of the visible characters. The combination rejects the
    spam ("Why" alone with 3 letters but 12.5% letter ratio) without
    hurting legit short titles ("Foo", "FRom", "M*A*S*H").
    """
    if not t:
        return False
    letters = "".join(c for c in t if c.isalpha())
    if len(letters) < 3:
        return False
    if len(letters) / max(len(t), 1) < 0.3:
        return False
    return True


def _quality_filter(items: list["TmdbItem"]) -> list["TmdbItem"]:
    """Drop items that have no poster OR a junk title.

    Trending / discover endpoints occasionally return entries without art
    (community uploads pending image review) or with spam titles. Both
    render badly in the row UI (gray ciak placeholder + unreadable label)
    so we filter them out at the API edge.
    """
    return [it for it in items if it.poster_url and _is_real_title(it.title)]


class TmdbClient:
    """Async TMDB v3 API client."""

    def __init__(self, *, api_key: str, http: Any, language: str = "it-IT", region: str = "IT") -> None:
        self._api_key = api_key
        self._http = http
        self._lang = language
        self._region = region

    def image_url(self, path: Optional[str], *, size: str = "w500") -> Optional[str]:
        if not path:
            return None
        return f"{_IMG_BASE}/{size}{path}"

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        params = params or {}
        params.setdefault("api_key", self._api_key)
        params.setdefault("language", self._lang)
        params.setdefault("region", self._region)
        url = f"{_BASE}{path}"
        resp = await self._http.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _parse_movie(self, data: dict) -> TmdbItem:
        return TmdbItem(
            tmdb_id=int(data["id"]),
            media_type="movie",
            title=data.get("title") or data.get("original_title") or "",
            original_title=data.get("original_title"),
            year=_parse_year(data.get("release_date")),
            poster_url=self.image_url(data.get("poster_path")),
            backdrop_url=self.image_url(data.get("backdrop_path"), size="w1280"),
            overview=data.get("overview") or None,
            rating=float(data["vote_average"]) if data.get("vote_average") is not None else None,
            runtime_minutes=data.get("runtime"),
            genres=[g["name"] for g in data.get("genres", [])] if "genres" in data else [],
            original_language=data.get("original_language"),
            origin_country=list(data.get("origin_country") or []),
            vote_count=int(data.get("vote_count") or 0),
            popularity=float(data.get("popularity") or 0.0),
        )

    def _parse_tv(self, data: dict) -> TmdbItem:
        return TmdbItem(
            tmdb_id=int(data["id"]),
            media_type="tv",
            title=data.get("name") or data.get("original_name") or "",
            original_title=data.get("original_name"),
            year=_parse_year(data.get("first_air_date")),
            poster_url=self.image_url(data.get("poster_path")),
            backdrop_url=self.image_url(data.get("backdrop_path"), size="w1280"),
            overview=data.get("overview") or None,
            rating=float(data["vote_average"]) if data.get("vote_average") is not None else None,
            seasons_count=data.get("number_of_seasons"),
            genres=[g["name"] for g in data.get("genres", [])] if "genres" in data else [],
            original_language=data.get("original_language"),
            origin_country=list(data.get("origin_country") or []),
            vote_count=int(data.get("vote_count") or 0),
            popularity=float(data.get("popularity") or 0.0),
        )

    def _parse_search_or_collection_item(self, data: dict, default_type: str = "movie") -> TmdbItem:
        # `media_type` is only present in /search/multi and /trending responses.
        # Otherwise we assume default_type from the endpoint.
        mt = data.get("media_type", default_type)
        if mt == "tv":
            return self._parse_tv(data)
        return self._parse_movie(data)

    async def popular_movies(self, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/movie/popular", {"page": page})
        return _quality_filter([self._parse_movie(x) for x in data.get("results", [])])

    async def popular_tv(self, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/tv/popular", {"page": page})
        return _quality_filter([self._parse_tv(x) for x in data.get("results", [])])

    async def top_rated_movies(self, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/movie/top_rated", {"page": page})
        return _quality_filter([self._parse_movie(x) for x in data.get("results", [])])

    async def top_rated_tv(self, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/tv/top_rated", {"page": page})
        return _quality_filter([self._parse_tv(x) for x in data.get("results", [])])

    async def trending_day(self, *, media_type: str = "all", page: int = 1) -> list[TmdbItem]:
        """``media_type`` is one of ``all``/``movie``/``tv``."""
        data = await self._get(f"/trending/{media_type}/day", {"page": page})
        default = "tv" if media_type == "tv" else "movie"
        items = [
            self._parse_search_or_collection_item(x, default_type=default)
            for x in data.get("results", [])
        ]
        return _quality_filter(items)

    async def trending_week(self, *, media_type: str = "all", page: int = 1) -> list[TmdbItem]:
        data = await self._get(f"/trending/{media_type}/week", {"page": page})
        default = "tv" if media_type == "tv" else "movie"
        items = [
            self._parse_search_or_collection_item(x, default_type=default)
            for x in data.get("results", [])
        ]
        return _quality_filter(items)

    async def discover_movies_by_genre(self, *, genre_ids: list[int], page: int = 1) -> list[TmdbItem]:
        data = await self._get("/discover/movie", {
            "with_genres": ",".join(str(g) for g in genre_ids),
            "with_origin_country": _WESTERN_COUNTRIES,
            "vote_count.gte": _VOTE_FLOOR,
            "include_adult": "false",
            "sort_by": "popularity.desc",
            "page": page,
        })
        return _quality_filter([self._parse_movie(x) for x in data.get("results", [])])

    async def discover_by_genre(
        self,
        *,
        genre_ids: list[int],
        media_type: str,
        original_language: str | None = None,
        origin: str = "western",
        page: int = 1,
    ) -> list[TmdbItem]:
        """Discover ``movie`` or ``tv`` items filtered by genre IDs.

        ``origin`` controls the country filter: ``western`` (default) uses the
        Western country list (the plugins don't cover Korean / Indian / Turkish
        catalogs); ``jp`` restricts to Japan — used by the Anime rows so they
        surface real Japanese anime instead of Western cartoons. Vote floor
        drops fresh-upload spam. Optional ``original_language`` lets rows like
        "Commedie italiane" constrain to a specific language (``it``).
        """
        if media_type not in ("movie", "tv"):
            raise ValueError("media_type must be 'movie' or 'tv'")
        country = "JP" if origin == "jp" else _WESTERN_COUNTRIES
        params: dict[str, Any] = {
            "with_genres": ",".join(str(g) for g in genre_ids),
            "with_origin_country": country,
            "vote_count.gte": _VOTE_FLOOR,
            "include_adult": "false",
            "sort_by": "popularity.desc",
            "page": page,
        }
        if original_language:
            params["with_original_language"] = original_language
        data = await self._get(f"/discover/{media_type}", params)
        parser = self._parse_movie if media_type == "movie" else self._parse_tv
        return _quality_filter([parser(x) for x in data.get("results", [])])

    async def new_releases(
        self,
        *,
        media_type: str,
        days: int = 60,
        page: int = 1,
    ) -> list[TmdbItem]:
        """Recent releases inside a ``days``-wide window, sorted by popularity.

        Was previously sorted by release date ascending — that surfaced
        every spam upload of the last hour ("★1★888★633★4176★ Why" etc.).
        Now we keep the date window but sort by popularity so legit new
        releases bubble up. Vote floor + Western-origin + poster filter
        drop the rest.
        """
        if media_type not in ("movie", "tv"):
            raise ValueError("media_type must be 'movie' or 'tv'")
        from datetime import UTC, datetime, timedelta

        today = datetime.now(UTC).date()
        floor = today - timedelta(days=days)
        common: dict[str, Any] = {
            "sort_by": "popularity.desc",
            "with_origin_country": _WESTERN_COUNTRIES,
            "vote_count.gte": _VOTE_FLOOR,
            "include_adult": "false",
            "page": page,
        }
        if media_type == "movie":
            params: dict[str, Any] = {
                **common,
                "primary_release_date.gte": floor.isoformat(),
                "primary_release_date.lte": today.isoformat(),
            }
        else:
            params = {
                **common,
                "first_air_date.gte": floor.isoformat(),
                "first_air_date.lte": today.isoformat(),
            }
        data = await self._get(f"/discover/{media_type}", params)
        parser = self._parse_movie if media_type == "movie" else self._parse_tv
        return _quality_filter([parser(x) for x in data.get("results", [])])

    async def similar(self, tmdb_id: int, *, media_type: str, page: int = 1) -> list[TmdbItem]:
        if media_type not in ("movie", "tv"):
            raise ValueError("media_type must be 'movie' or 'tv'")
        data = await self._get(f"/{media_type}/{tmdb_id}/similar", {"page": page})
        parser = self._parse_movie if media_type == "movie" else self._parse_tv
        return [parser(x) for x in data.get("results", [])]

    async def recommendations(self, tmdb_id: int, *, media_type: str, page: int = 1) -> list[TmdbItem]:
        if media_type not in ("movie", "tv"):
            raise ValueError("media_type must be 'movie' or 'tv'")
        data = await self._get(f"/{media_type}/{tmdb_id}/recommendations", {"page": page})
        parser = self._parse_movie if media_type == "movie" else self._parse_tv
        return [parser(x) for x in data.get("results", [])]

    async def discover_anime(self, *, page: int = 1) -> list[TmdbItem]:
        # Anime: TV with genre 16 (Animation) + origin country JP. Keep the
        # JP filter — anime IS the intended exception to the Western default.
        data = await self._get("/discover/tv", {
            "with_genres": "16",
            "with_origin_country": "JP",
            "vote_count.gte": _VOTE_FLOOR,
            "sort_by": "popularity.desc",
            "page": page,
        })
        return _quality_filter([self._parse_tv(x) for x in data.get("results", [])])

    async def get_movie(self, tmdb_id: int) -> TmdbItem:
        data = await self._get(f"/movie/{tmdb_id}")
        return self._parse_movie(data)

    async def get_tv(self, tmdb_id: int) -> TmdbItem:
        data = await self._get(f"/tv/{tmdb_id}")
        return self._parse_tv(data)

    async def get_tv_season(self, tmdb_id: int, season_number: int) -> dict:
        """Raw season payload — caller picks the fields it cares about."""
        return await self._get(f"/tv/{tmdb_id}/season/{season_number}")

    async def get_videos(self, tmdb_id: int, *, media_type: str) -> list[dict]:
        """Raw videos payload (``results`` array) for movie or tv.

        We do NOT localise this call — many titles only have an English
        trailer registered, and asking TMDB for ``it-IT`` returns an empty
        list. Callers can filter by ``site`` / ``type`` / ``official``.
        """
        data = await self._get(
            f"/{media_type}/{tmdb_id}/videos",
            {"language": "en-US"},
        )
        return list(data.get("results", []))

    async def get_logo_url(self, tmdb_id: int, *, media_type: str) -> Optional[str]:
        """Best official title-logo (transparent PNG) for a movie/tv, or None.

        TMDB ``/images`` filters logos to the request ``language`` *unless*
        ``include_image_language`` lists them explicitly, so we ask for
        Italian, English and language-neutral logos in one call. Preference
        order: Italian → English → language-neutral → first available. Logos
        are the studio's typographic title treatment — used by the hero so a
        film shows its real wordmark instead of app-rendered text.
        """
        data = await self._get(
            f"/{media_type}/{tmdb_id}/images",
            {"include_image_language": "it,en,null", "language": "it"},
        )
        logos = data.get("logos") or []
        if not logos:
            return None

        def _rank(logo: dict) -> int:
            iso = logo.get("iso_639_1")
            if iso == "it":
                return 0
            if iso == "en":
                return 1
            if iso in (None, ""):
                return 2
            return 3

        best = min(logos, key=_rank)
        return self.image_url(best.get("file_path"), size="w500")

    async def get_credits(self, tmdb_id: int, *, media_type: str) -> dict:
        """Raw credits payload (``cast`` + ``crew`` arrays) for movie or tv.

        Localised to the client's default (``it-IT``) so character names
        come back in Italian when TMDB has them. Callers are expected to
        cap ``cast`` and filter ``crew`` to the jobs they care about.
        """
        return await self._get(f"/{media_type}/{tmdb_id}/credits")

    async def get_person(self, person_id: int) -> dict:
        """Raw ``/person/{id}`` payload — bio + birthday + profile path.

        ``append_to_response=images`` pulls additional profile photos in
        the same round-trip so a future "photo gallery" on the person
        page doesn't need a second call. We return the raw dict; the API
        route shapes it into a PersonResponse.
        """
        return await self._get(
            f"/person/{person_id}",
            {"append_to_response": "images"},
        )

    async def get_person_credits(self, person_id: int) -> dict:
        """Raw ``/person/{id}/combined_credits`` payload (cast + crew).

        Combined endpoint returns movies AND tv together with a
        ``media_type`` discriminator on each entry — perfect for the
        Filmografia row that mixes both. API route handles dedup +
        quality filter + popularity sort.
        """
        return await self._get(f"/person/{person_id}/combined_credits")

    async def search_multi(self, query: str, *, page: int = 1) -> list[TmdbItem]:
        data = await self._get("/search/multi", {"query": query, "page": page})
        results = []
        for x in data.get("results", []):
            mt = x.get("media_type")
            if mt not in ("movie", "tv"):
                continue
            results.append(self._parse_search_or_collection_item(x))
        return results

    def _parse_person(self, data: dict) -> TmdbPerson:
        # `known_for` carries up to 3 of the person's most famous titles.
        # Movies expose `title`, tv exposes `name`.
        known_for_titles = []
        for kf in data.get("known_for", []) or []:
            name = kf.get("title") or kf.get("name")
            if name:
                known_for_titles.append(name)
        return TmdbPerson(
            tmdb_id=int(data["id"]),
            name=data.get("name") or "",
            profile_url=self.image_url(data.get("profile_path")),
            known_for_department=data.get("known_for_department"),
            known_for_titles=known_for_titles,
        )

    async def search_multi_all(self, query: str, *, page: int = 1) -> dict:
        """Parse BOTH titles and people from /search/multi.

        Returns ``{"titles": list[TmdbItem], "people": list[TmdbPerson]}``.
        People without a profile photo are still included (the client shows
        a fallback avatar), but crew with a department outside
        ``_PEOPLE_DEPARTMENTS`` AND no notable credits are dropped — those
        are typically TMDB noise the operator never wants surfaced.
        """
        data = await self._get("/search/multi", {"query": query, "page": page})
        titles: list[TmdbItem] = []
        people: list[TmdbPerson] = []
        for x in data.get("results", []):
            mt = x.get("media_type")
            if mt in ("movie", "tv"):
                titles.append(self._parse_search_or_collection_item(x))
            elif mt == "person":
                person = self._parse_person(x)
                if (person.known_for_department not in _PEOPLE_DEPARTMENTS
                        and not person.known_for_titles):
                    continue
                people.append(person)

        # Drop "people" whose name is literally a title in the results — that's
        # a franchise mis-tagged as a person (e.g. searching "avengers" returns
        # a bogus person "The Avengers"). Real actors never collide with a
        # title name here.
        _title_names = {(t.title or "").strip().lower() for t in titles}
        people = [
            p for p in people
            if (p.name or "").strip().lower() not in _title_names
        ]

        # ── Relevance algorithm ───────────────────────────────────────────
        # A serious, Netflix-style ranking from the strong signals TMDB gives
        # us at search time (it does NOT return genres here). Three factors:
        #   1. title match  — exact > prefix > contains > all-words > any-word
        #   2. popularity   — separates the real films from the long tail
        #   3. quality      — vote_average (rating) gated by vote_count, so a
        #                     1-vote 10/10 never beats a 7.8 with 50k votes
        # …plus a QUALITY GATE that drops posterless / spam / obscure noise
        # (the comics, Lego sets and "Elon Musk: Real Life Iron Man" clutter).
        ql = query.strip().lower()
        qtokens = {w for w in ql.split() if w}

        def _match(it: TmdbItem) -> float:
            t = (it.title or "").lower()
            if not ql:
                return 0.0
            if t == ql:
                return 1_000_000.0
            if t.startswith(ql):
                return 400_000.0
            if ql in t:
                return 150_000.0
            tw = set(t.split())
            if qtokens and qtokens.issubset(tw):
                return 90_000.0
            if qtokens & tw:
                return 25_000.0
            return 0.0

        def _quality(it: TmdbItem) -> float:
            rating = float(it.rating or 0.0)
            votes = int(it.vote_count or 0)
            # Confidence-weighted rating: a film needs an audience for its
            # score to count fully (caps the weight at ~1k votes).
            return rating * min(votes, 1000) / 1000.0

        def _score(it: TmdbItem) -> float:
            return (
                _match(it)
                + float(it.popularity or 0.0) * 60.0
                + _quality(it) * 4_000.0
                + min(int(it.vote_count or 0), 20_000) * 0.15
            )

        def _keep(it: TmdbItem) -> bool:
            # Always need real art + a real title.
            if not it.poster_url or not _is_real_title(it.title):
                return False
            t = (it.title or "").lower()
            # Exact / prefix matches are the films the user means — always keep.
            if t == ql or t.startswith(ql):
                return True
            # Weaker matches must have a real audience to make the cut.
            return int(it.vote_count or 0) >= 50

        titles = [it for it in titles if _keep(it)]
        titles.sort(key=_score, reverse=True)
        return {"titles": titles, "people": people}
