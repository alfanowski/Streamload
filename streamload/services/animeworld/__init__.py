"""AnimeWorld service plugin for Streamload.

AnimeWorld is a popular Italian anime streaming site that serves content
via direct MP4 downloads through the SweetPixel player.  Search is
performed by scraping the HTML search results page.

Registration::

    @ServiceRegistry.register
    class AnimeWorldService(ServiceBase): ...

The service is automatically discovered by
:func:`streamload.services.load_services` when it imports the
``streamload.services.animeworld`` package.
"""

from __future__ import annotations

from streamload.models.media import (
    Episode,
    MediaEntry,
    MediaType,
    Season,
    ServiceCategory,
)
from streamload.models.stream import StreamBundle
from streamload.player import sweetpixel
from streamload.services import ServiceRegistry
from streamload.services.base import ServiceBase
from streamload.utils.logger import get_logger

from .extractor import extract_streams
from .scraper import get_episodes, search_anime

log = get_logger(__name__)


@ServiceRegistry.register
class AnimeWorldService(ServiceBase):
    """AnimeWorld (www.animeworld.it) service plugin.

    Supports searching, browsing episodes, and resolving direct MP4
    download links for anime content.  Like AnimeUnity, AnimeWorld does
    not use a traditional season model -- all episodes belong to a
    single implicit season.
    """

    name = "AnimeWorld"
    short_name = "aw"
    domains = ["www.animeworld.it"]
    category = ServiceCategory.ANIME
    language = "it"
    requires_login = False

    def __init__(self, http_client):
        super().__init__(http_client)
        # Cache session credentials across calls.
        self._session_id: str | None = None
        self._csrf_token: str | None = None

    # -- Internal helpers ---------------------------------------------------

    def _ensure_session(self) -> tuple[str, str]:
        """Obtain or reuse AnimeWorld session credentials.

        Returns ``(session_id, csrf_token)``.
        """
        if self._session_id is None or self._csrf_token is None:
            self._session_id, self._csrf_token = sweetpixel.get_session_and_csrf(
                self._http, self.base_url,
            )
        return self._session_id, self._csrf_token

    # -- ServiceBase interface ----------------------------------------------

    def search(self, query: str) -> list[MediaEntry]:
        """Search AnimeWorld for anime matching *query*.

        Returns :class:`MediaEntry` results parsed from the HTML search
        page.
        """
        raw_anime = search_anime(self._http, self.base_url, query)

        entries: list[MediaEntry] = []
        for anime in raw_anime:
            entries.append(
                MediaEntry(
                    id=anime.url,  # Use URL as ID (AnimeWorld has no numeric IDs in search)
                    title=anime.name,
                    type=MediaType.ANIME,
                    url=anime.url,
                    service=self.short_name,
                    image_url=anime.image_url,
                )
            )

        log.info("search(%r) -> %d entries", query, len(entries))
        return entries

    def get_seasons(self, entry: MediaEntry) -> list[Season]:
        """Return a single implicit season for the anime.

        AnimeWorld does not organise content into seasons; all episodes
        belong to one flat list.  We return a single :class:`Season`
        with ``number=1``.
        """
        session_id, csrf_token = self._ensure_session()
        episodes = get_episodes(
            self._http, entry.url, session_id, csrf_token,
        )

        return [
            Season(
                number=1,
                episode_count=len(episodes),
                title="All Episodes",
                id=entry.url,  # Encode the anime URL for get_episodes()
            )
        ]

    def get_episodes(self, season: Season) -> list[Episode]:
        """Fetch episodes for the anime.

        Since AnimeWorld has no seasons, ``season.id`` contains the
        anime URL set by :meth:`get_seasons`.
        """
        anime_url = str(season.id)
        session_id, csrf_token = self._ensure_session()
        raw_episodes = get_episodes(
            self._http, anime_url, session_id, csrf_token,
        )

        episodes: list[Episode] = []
        for idx, ep in enumerate(raw_episodes, start=1):
            ep_number = int(ep.number) if ep.number.isdigit() else idx
            episodes.append(
                Episode(
                    number=ep_number,
                    season_number=1,
                    title=f"Episode {ep.number}",
                    url=anime_url,
                    id=ep.id,
                )
            )

        episodes.sort(key=lambda e: e.number)
        log.info("get_episodes(%s) -> %d episode(s)", anime_url, len(episodes))
        return episodes

    def get_streams(self, item: Episode | MediaEntry) -> StreamBundle:
        """Resolve MP4 download URL for an anime episode.

        Delegates to :mod:`.extractor` which in turn uses the
        :mod:`streamload.player.sweetpixel` module.
        """
        session_id, csrf_token = self._ensure_session()

        if isinstance(item, Episode):
            episode_id = str(item.id) if item.id else ""
            return extract_streams(
                self._http,
                self.base_url,
                episode_id,
                session_id,
                csrf_token,
            )

        # MediaEntry -- treat as single-episode anime (film/OVA).
        # Fetch the first episode and resolve its stream.
        raw_episodes = get_episodes(
            self._http, item.url, session_id, csrf_token,
        )
        if not raw_episodes:
            from streamload.core.exceptions import ServiceError
            raise ServiceError(
                f"No episodes found for {item.title}",
                service_name="animeworld",
            )

        return extract_streams(
            self._http,
            self.base_url,
            raw_episodes[0].id,
            session_id,
            csrf_token,
        )
