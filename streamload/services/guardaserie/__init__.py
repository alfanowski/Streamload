"""GuardaSerie service plugin for Streamload.

GuardaSerie is an Italian TV series streaming aggregator.  It uses
traditional HTML scraping for search and season/episode browsing, with
the SuperVideo player for HLS streaming.

Registration::

    @ServiceRegistry.register
    class GuardaSerieService(ServiceBase): ...

The service is automatically discovered by
:func:`streamload.services.load_services` when it imports the
``streamload.services.guardaserie`` package.
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
from .scraper import get_season_episodes, get_seasons_count, search_series

log = get_logger(__name__)


@ServiceRegistry.register
class GuardaSerieService(ServiceBase):
    """GuardaSerie (guardaserie.moe) service plugin.

    Supports searching, browsing seasons/episodes, and resolving HLS
    streams for TV series content via the SuperVideo player.
    """

    name = "GuardaSerie"
    short_name = "gs"
    domains = ["guardaserie.moe"]
    category = ServiceCategory.SERIE
    language = "it"
    requires_login = False

    # -- ServiceBase interface ----------------------------------------------

    def search(self, query: str) -> list[MediaEntry]:
        """Search GuardaSerie for series matching *query*.

        Returns :class:`MediaEntry` results parsed from the HTML search
        page.
        """
        raw_series = search_series(self._http, self.base_url, query)

        entries: list[MediaEntry] = []
        for serie in raw_series:
            entries.append(
                MediaEntry(
                    id=serie.url,  # URL as identifier
                    title=serie.name,
                    type=MediaType.SERIE,
                    url=serie.url,
                    service=self.short_name,
                    image_url=serie.image_url,
                )
            )

        log.info("search(%r) -> %d entries", query, len(entries))
        return entries

    def get_seasons(self, entry: MediaEntry) -> list[Season]:
        """Fetch seasons for a series :class:`MediaEntry`."""
        series_url = entry.url
        title, season_count = get_seasons_count(self._http, series_url)

        seasons: list[Season] = []
        for n in range(1, season_count + 1):
            seasons.append(
                Season(
                    number=n,
                    title=f"Season {n}",
                    id=series_url,  # Encode series URL for get_episodes()
                )
            )

        log.info("get_seasons(%s) -> %d season(s)", entry.title, len(seasons))
        return seasons

    def get_episodes(self, season: Season) -> list[Episode]:
        """Fetch episodes for a :class:`Season`.

        ``season.id`` contains the series URL set by :meth:`get_seasons`.
        """
        series_url = str(season.id)
        raw_episodes = get_season_episodes(
            self._http, series_url, season.number,
        )

        episodes: list[Episode] = []
        for ep in raw_episodes:
            ep_number = int(ep.number) if ep.number.isdigit() else 0
            # Encode the player URL and fallback into the episode ID.
            # Format: "{primary_url}|{fallback_url_or_empty}"
            encoded_id = f"{ep.url}|{ep.fallback_url or ''}"

            episodes.append(
                Episode(
                    number=ep_number,
                    season_number=season.number,
                    title=ep.name,
                    url=series_url,
                    id=encoded_id,
                )
            )

        episodes.sort(key=lambda e: e.number)
        log.info(
            "get_episodes(season %d) -> %d episode(s)",
            season.number, len(episodes),
        )
        return episodes

    def get_streams(self, item: Episode | MediaEntry) -> StreamBundle:
        """Resolve HLS streams for a series episode.

        Delegates to :mod:`.extractor` which in turn uses the
        :mod:`streamload.player.supervideo` module.
        """
        if isinstance(item, Episode):
            # Decode the player URLs from episode ID.
            parts = str(item.id).split("|", 1)
            player_url = parts[0]
            fallback_url = parts[1] if len(parts) > 1 and parts[1] else None

            return extract_streams(
                self._http,
                player_url,
                fallback_url=fallback_url,
            )

        # MediaEntry -- GuardaSerie is series-only; this shouldn't happen
        # but handle gracefully.
        from streamload.core.exceptions import ServiceError
        raise ServiceError(
            "GuardaSerie is a series-only service; use get_seasons/get_episodes first",
            service_name="guardaserie",
        )
