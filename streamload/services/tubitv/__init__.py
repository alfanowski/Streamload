"""TubiTV service plugin for Streamload.

TubiTV is a free ad-supported streaming service available primarily in
the US.  It provides HLS streams with optional Widevine DRM.  Search and
metadata are fetched via JSON APIs; authentication requires an email
and password to obtain a bearer token.

Registration::

    @ServiceRegistry.register
    class TubiTVService(ServiceBase): ...

The service is automatically discovered by
:func:`streamload.services.load_services` when it imports the
``streamload.services.tubitv`` package.
"""

from __future__ import annotations

import re

from streamload.models.media import (
    Episode,
    MediaEntry,
    MediaType,
    Season,
    ServiceCategory,
)
from streamload.models.stream import StreamBundle
from streamload.services import ServiceRegistry
from streamload.services.base import ServiceBase
from streamload.utils.logger import get_logger

from .extractor import extract_streams, get_bearer_token
from .scraper import get_series_seasons, search_titles

log = get_logger(__name__)


def _extract_content_id(url: str) -> str | None:
    """Extract the content ID from a TubiTV URL.

    URL patterns:
    - ``https://tubitv.com/series/{id}/{slug}``
    - ``https://tubitv.com/movies/{id}/{slug}``
    """
    match = re.search(r"/(?:series|movies)/(\d+)/", url)
    return match.group(1) if match else None


@ServiceRegistry.register
class TubiTVService(ServiceBase):
    """TubiTV (tubitv.com) service plugin.

    Supports searching, browsing seasons/episodes, and resolving HLS
    streams for both films and TV series.  Requires authentication
    credentials to obtain a bearer token for API access.
    """

    name = "TubiTV"
    short_name = "tb"
    domains = ["tubitv.com"]
    category = ServiceCategory.SERIE
    language = "en"
    requires_login = False

    def __init__(self, http_client):
        super().__init__(http_client)
        self._bearer_token: str | None = None
        self._seasons_cache: dict[str, dict[int, list]] = {}

    # -- Internal helpers ---------------------------------------------------

    def _ensure_token(self) -> str:
        """Obtain or reuse the TubiTV bearer token.

        If credentials are available through :meth:`authenticate`, uses
        them; otherwise attempts authentication with session credentials.
        """
        if self._bearer_token:
            return self._bearer_token

        email: str | None = None
        password: str | None = None
        if self._session:
            email = self._session.headers.get("email")
            password = self._session.headers.get("password")

        self._bearer_token = get_bearer_token(
            self._http, email=email, password=password,
        )
        return self._bearer_token

    # -- ServiceBase interface ----------------------------------------------

    def authenticate(self, credentials: dict[str, str]):
        """Authenticate with TubiTV using email/password.

        Parameters
        ----------
        credentials:
            Must contain ``"email"`` and ``"password"`` keys.
        """
        from streamload.models.media import AuthSession
        email = credentials.get("email", "")
        password = credentials.get("password", "")

        self._bearer_token = get_bearer_token(
            self._http, email=email, password=password,
        )

        self._session = AuthSession(
            headers={"email": email, "password": password},
        )
        return self._session

    def search(self, query: str) -> list[MediaEntry]:
        """Search TubiTV for titles matching *query*.

        Returns :class:`MediaEntry` results sorted by relevance.
        """
        token = self._ensure_token()
        raw_titles = search_titles(self._http, query, token)

        entries: list[MediaEntry] = []
        for t in raw_titles:
            media_type = MediaType.SERIE if t.type == "tv" else MediaType.FILM

            year: int | None = None
            if t.year and t.year != "9999":
                try:
                    year = int(t.year)
                except ValueError:
                    pass

            entries.append(
                MediaEntry(
                    id=t.id,
                    title=t.title,
                    type=media_type,
                    url=t.url,
                    service=self.short_name,
                    year=year,
                    image_url=t.image_url,
                )
            )

        log.info("search(%r) -> %d entries", query, len(entries))
        return entries

    def get_seasons(self, entry: MediaEntry) -> list[Season]:
        """Fetch seasons for a series :class:`MediaEntry`.

        For films, returns an empty list.
        """
        if entry.type == MediaType.FILM:
            return []

        content_id = _extract_content_id(entry.url) or entry.id
        token = self._ensure_token()
        seasons_data = get_series_seasons(self._http, content_id, token)

        # Cache for get_episodes().
        self._seasons_cache[content_id] = seasons_data

        seasons: list[Season] = []
        for season_num in sorted(seasons_data.keys()):
            eps = seasons_data[season_num]
            seasons.append(
                Season(
                    number=season_num,
                    episode_count=len(eps),
                    title=f"Season {season_num}",
                    id=f"{content_id}:{season_num}",
                )
            )

        log.info("get_seasons(%s) -> %d season(s)", entry.title, len(seasons))
        return seasons

    def get_episodes(self, season: Season) -> list[Episode]:
        """Fetch episodes for a :class:`Season`.

        ``season.id`` encodes ``"{content_id}:{season_number}"``
        (set by :meth:`get_seasons`).
        """
        parts = str(season.id).split(":")
        content_id = parts[0]
        season_number = int(parts[1]) if len(parts) > 1 else season.number

        # Try cache first.
        cached = self._seasons_cache.get(content_id, {})
        raw_episodes = cached.get(season_number, [])

        if not raw_episodes:
            # Re-fetch if not cached.
            token = self._ensure_token()
            all_seasons = get_series_seasons(self._http, content_id, token)
            self._seasons_cache[content_id] = all_seasons
            raw_episodes = all_seasons.get(season_number, [])

        episodes: list[Episode] = []
        for ep in raw_episodes:
            episodes.append(
                Episode(
                    number=ep.number,
                    season_number=season_number,
                    title=ep.title,
                    url=f"https://tubitv.com/series/{content_id}",
                    id=ep.id,
                    duration=ep.duration,
                )
            )

        episodes.sort(key=lambda e: e.number)
        log.info(
            "get_episodes(season %d) -> %d episode(s)",
            season_number, len(episodes),
        )
        return episodes

    def get_streams(self, item: Episode | MediaEntry) -> StreamBundle:
        """Resolve HLS streams for a film or episode.

        Calls the TubiTV content API to obtain the HLS manifest URL
        and optional Widevine licence URL.
        """
        token = self._ensure_token()

        if isinstance(item, Episode):
            content_id = str(item.id) if item.id else ""
        else:
            content_id = _extract_content_id(item.url) or item.id

        return extract_streams(self._http, content_id, token)
