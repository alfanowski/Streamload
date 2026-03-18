"""Discovery+ service plugin for Streamload.

Discovery+ is a streaming service offering content from Discovery
networks (DMAX, Real Time, Food Network, etc.).  It provides DASH/HLS
streams protected with Widevine or PlayReady DRM.

The service supports both anonymous access (limited catalogue) and
authenticated access via an ``st`` cookie.

Registration::

    @ServiceRegistry.register
    class DiscoveryPlusService(ServiceBase): ...

The service is automatically discovered by
:func:`streamload.services.load_services` when it imports the
``streamload.services.discovery`` package.
"""

from __future__ import annotations

from streamload.models.media import (
    AuthSession,
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

from .extractor import extract_streams
from .scraper import DiscoveryClient, get_client, get_show_episodes, search_titles

log = get_logger(__name__)


@ServiceRegistry.register
class DiscoveryPlusService(ServiceBase):
    """Discovery+ (discoveryplus.com) service plugin.

    Supports searching, browsing seasons/episodes, and resolving
    DASH/HLS streams with DRM for shows and videos.  Works in both
    anonymous and authenticated modes.
    """

    name = "Discovery+"
    short_name = "dc"
    domains = ["discoveryplus.com"]
    category = ServiceCategory.FILM_SERIE
    language = "it"
    requires_login = False

    def __init__(self, http_client):
        super().__init__(http_client)
        self._client: DiscoveryClient | None = None
        self._episodes_cache: dict[str, list] = {}

    # -- Internal helpers ---------------------------------------------------

    def _ensure_client(self) -> DiscoveryClient:
        """Get or create the Discovery+ client."""
        if self._client is None:
            st_cookie: str | None = None
            if self._session:
                st_cookie = self._session.cookies.get("st")
            self._client = get_client(self._http, st_cookie)
        return self._client

    # -- ServiceBase interface ----------------------------------------------

    def authenticate(self, credentials: dict[str, str]) -> AuthSession | None:
        """Authenticate with Discovery+ using an ``st`` cookie.

        Parameters
        ----------
        credentials:
            Must contain an ``"st"`` key with the session token value.
        """
        st_cookie = credentials.get("st", "")
        if not st_cookie:
            return None

        self._client = DiscoveryClient(self._http, st_cookie)
        self._session = AuthSession(cookies={"st": st_cookie})
        return self._session

    def search(self, query: str) -> list[MediaEntry]:
        """Search Discovery+ for titles matching *query*.

        Returns :class:`MediaEntry` results from both shows and videos.
        """
        client = self._ensure_client()
        raw_titles = search_titles(self._http, client, query)

        entries: list[MediaEntry] = []
        for t in raw_titles:
            media_type = MediaType.SERIE if t.type == "tv" else MediaType.FILM

            year: int | None = None
            if t.year:
                try:
                    year = int(t.year)
                except ValueError:
                    pass

            entries.append(
                MediaEntry(
                    id=t.id,
                    title=t.name,
                    type=media_type,
                    url=t.id,  # alternateId or video ID
                    service=self.short_name,
                    year=year,
                    image_url=t.image_url,
                )
            )

        log.info("search(%r) -> %d entries", query, len(entries))
        return entries

    def get_seasons(self, entry: MediaEntry) -> list[Season]:
        """Fetch seasons for a series :class:`MediaEntry`.

        For films / standalone videos, returns an empty list.
        """
        if entry.type == MediaType.FILM:
            return []

        client = self._ensure_client()
        show_id = entry.id
        show_name, all_episodes = get_show_episodes(self._http, client, show_id)

        # Cache episodes for get_episodes().
        self._episodes_cache[show_id] = all_episodes

        # Build seasons from distinct season numbers.
        seasons_map: dict[int, int] = {}
        for ep in all_episodes:
            seasons_map[ep.season_number] = seasons_map.get(ep.season_number, 0) + 1

        seasons: list[Season] = []
        for season_num in sorted(seasons_map.keys()):
            seasons.append(
                Season(
                    number=season_num,
                    episode_count=seasons_map[season_num],
                    title=f"Season {season_num}",
                    id=f"{show_id}:{season_num}",
                )
            )

        log.info("get_seasons(%s) -> %d season(s)", show_name, len(seasons))
        return seasons

    def get_episodes(self, season: Season) -> list[Episode]:
        """Fetch episodes for a :class:`Season`.

        ``season.id`` encodes ``"{show_id}:{season_number}"``
        (set by :meth:`get_seasons`).
        """
        parts = str(season.id).split(":")
        show_id = parts[0]
        season_number = int(parts[1]) if len(parts) > 1 else season.number

        # Use cached episodes if available.
        all_episodes = self._episodes_cache.get(show_id, [])
        if not all_episodes:
            client = self._ensure_client()
            _, all_episodes = get_show_episodes(self._http, client, show_id)
            self._episodes_cache[show_id] = all_episodes

        episodes: list[Episode] = []
        for ep in all_episodes:
            if ep.season_number != season_number:
                continue

            episodes.append(
                Episode(
                    number=ep.episode_number,
                    season_number=season_number,
                    title=ep.title,
                    url=show_id,
                    id=ep.id,  # edit ID for playback
                )
            )

        episodes.sort(key=lambda e: e.number)
        log.info(
            "get_episodes(season %d) -> %d episode(s)",
            season_number, len(episodes),
        )
        return episodes

    def get_streams(self, item: Episode | MediaEntry) -> StreamBundle:
        """Resolve DASH/HLS streams for a show episode or video.

        Delegates to :mod:`.extractor` to call the Discovery+ playback
        orchestration API and extract manifest + DRM info.
        """
        client = self._ensure_client()

        if isinstance(item, Episode):
            edit_id = str(item.id) if item.id else ""
        else:
            edit_id = item.id

        return extract_streams(self._http, client, edit_id)
