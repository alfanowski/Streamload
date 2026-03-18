"""AnimeUnity service plugin for Streamload.

AnimeUnity is a popular Italian anime streaming site.  It uses
CSRF-protected search endpoints (livesearch + archivio) and the VixCloud
video player for HLS streaming.

Registration::

    @ServiceRegistry.register
    class AnimeUnityService(ServiceBase): ...

The service is automatically discovered by
:func:`streamload.services.load_services` when it imports the
``streamload.services.animeunity`` package.
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
from streamload.services import ServiceRegistry
from streamload.services.base import ServiceBase
from streamload.utils.logger import get_logger

from .extractor import extract_streams
from .scraper import get_episodes, search_anime

log = get_logger(__name__)


@ServiceRegistry.register
class AnimeUnityService(ServiceBase):
    """AnimeUnity (animeunity.so) service plugin.

    Supports searching, browsing episodes, and resolving HLS streams for
    anime content.  AnimeUnity does not use a traditional season model --
    all episodes belong to a single implicit season.
    """

    name = "AnimeUnity"
    short_name = "au"
    domains = ["animeunity.so"]
    category = ServiceCategory.ANIME
    language = "it"
    requires_login = False

    # -- ServiceBase interface ----------------------------------------------

    def search(self, query: str) -> list[MediaEntry]:
        """Search AnimeUnity for anime matching *query*.

        Returns de-duplicated :class:`MediaEntry` results from both
        ``livesearch`` and ``archivio`` endpoints.
        """
        raw_anime = search_anime(self._http, self.base_url, query)

        entries: list[MediaEntry] = []
        for anime in raw_anime:
            anime_url = f"{self.base_url}/anime/{anime.id}-{anime.slug}"

            entries.append(
                MediaEntry(
                    id=str(anime.id),
                    title=anime.name,
                    type=MediaType.ANIME,
                    url=anime_url,
                    service=self.short_name,
                    image_url=anime.image_url,
                )
            )

        log.info("search(%r) -> %d entries", query, len(entries))
        return entries

    def get_seasons(self, entry: MediaEntry) -> list[Season]:
        """Return a single implicit season for the anime.

        AnimeUnity does not organise content into seasons; all episodes
        belong to one flat list.  We return a single :class:`Season`
        with ``number=1``.
        """
        media_id = int(entry.id)
        episodes = get_episodes(self._http, self.base_url, media_id)

        return [
            Season(
                number=1,
                episode_count=len(episodes),
                title="All Episodes",
                id=entry.id,  # media_id encoded as season id
            )
        ]

    def get_episodes(self, season: Season) -> list[Episode]:
        """Fetch episodes for the anime.

        Since AnimeUnity has no seasons, ``season.id`` contains the
        anime ``media_id`` set by :meth:`get_seasons`.
        """
        media_id = int(season.id)
        raw_episodes = get_episodes(self._http, self.base_url, media_id)

        episodes: list[Episode] = []
        for ep in raw_episodes:
            ep_number = int(float(ep.number)) if ep.number else 0
            episodes.append(
                Episode(
                    number=ep_number,
                    season_number=1,
                    title=f"Episode {ep.number}",
                    url=f"{self.base_url}/anime/{media_id}",
                    id=str(ep.id),
                )
            )

        episodes.sort(key=lambda e: e.number)
        log.info("get_episodes(anime %d) -> %d episode(s)", media_id, len(episodes))
        return episodes

    def get_streams(self, item: Episode | MediaEntry) -> StreamBundle:
        """Resolve HLS streams for an anime episode or film.

        Delegates to :mod:`.extractor` which in turn uses the
        :mod:`streamload.player.vixcloud` module.
        """
        if isinstance(item, Episode):
            episode_id = int(item.id) if item.id else None
            # Extract media_id from the episode URL.
            media_id = self._extract_media_id(item.url)
            return extract_streams(
                self._http,
                self.base_url,
                media_id,
                episode_id=episode_id,
            )

        # MediaEntry (anime film / OVA)
        media_id = int(item.id)
        return extract_streams(self._http, self.base_url, media_id)

    # -- Private helpers ----------------------------------------------------

    @staticmethod
    def _extract_media_id(url: str) -> int:
        """Extract the numeric media ID from an AnimeUnity URL.

        URL format: ``https://animeunity.so/anime/{id}-{slug}``
        """
        path = url.rstrip("/").split("/")[-1]
        id_part = path.split("-")[0]
        return int(id_part)
