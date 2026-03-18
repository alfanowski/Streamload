"""RaiPlay service plugin for Streamload.

RaiPlay is the free streaming platform of RAI (Radiotelevisione Italiana),
offering films, TV series, documentaries, and live broadcasts.  Content
is primarily in Italian.

Search uses the Atomatic JSON POST search API.  Season/episode metadata
is extracted from the program JSON descriptors.  Streams are resolved
through the MediaPolisVod relinker service, producing either non-DRM
HLS playlists or DRM-protected DASH manifests (Widevine).

Registration::

    @ServiceRegistry.register
    class RaiPlayService(ServiceBase): ...
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

from .extractor import extract_streams_for_film, extract_streams_from_url
from .scraper import (
    get_program_seasons,
    get_season_episodes,
    search_titles,
)

log = get_logger(__name__)


@ServiceRegistry.register
class RaiPlayService(ServiceBase):
    """RaiPlay (www.raiplay.it) service plugin.

    Supports searching, browsing seasons/episodes, and resolving
    HLS/DASH streams for both films and TV series.
    """

    name = "RaiPlay"
    short_name = "rp"
    domains = ["www.raiplay.it"]
    category = ServiceCategory.FILM_SERIE
    language = "it"
    requires_login = False

    # -- ServiceBase interface ----------------------------------------------

    def search(self, query: str) -> list[MediaEntry]:
        """Search RaiPlay via the Atomatic search API."""
        raw_titles = search_titles(self._http, query)

        entries: list[MediaEntry] = []
        for t in raw_titles:
            # RaiPlay content is treated as series by default;
            # films are detected later via the program structure.
            media_type = MediaType.SERIE

            year_int: int | None = None
            if t.year:
                try:
                    year_int = int(t.year)
                except (ValueError, TypeError):
                    year_int = None

            entries.append(
                MediaEntry(
                    id=t.path_id,
                    title=t.name,
                    type=media_type,
                    url=t.url,
                    service=self.short_name,
                    year=year_int,
                    image_url=t.image_url,
                )
            )

        log.info("search(%r) -> %d entries", query, len(entries))
        return entries

    def get_seasons(self, entry: MediaEntry) -> list[Season]:
        """Fetch seasons from the program JSON content blocks.

        The ``entry.id`` is the RaiPlay ``path_id`` pointing to the
        program JSON descriptor.
        """
        if entry.type == MediaType.FILM:
            return []

        path_id = entry.id
        series_name, raw_seasons = get_program_seasons(self._http, path_id)

        # If no seasons found, this may be a film or single-item content.
        if not raw_seasons:
            log.info("No seasons found for %s -- might be a film", path_id)
            return []

        seasons: list[Season] = []
        for rs in raw_seasons:
            # Encode routing info: "set_id:block_id:path_id"
            encoded_id = f"{rs.set_id}:{rs.block_id}:{path_id}"

            seasons.append(
                Season(
                    number=rs.number,
                    id=encoded_id,
                    title=rs.name or f"Season {rs.number}",
                    episode_count=rs.episode_count,
                )
            )

        seasons.sort(key=lambda s: s.number)
        log.info("get_seasons(%s) -> %d season(s)", entry.id, len(seasons))
        return seasons

    def get_episodes(self, season: Season) -> list[Episode]:
        """Fetch episodes for a season.

        The ``season.id`` is encoded by :meth:`get_seasons` as
        ``"set_id:block_id:path_id"`` to carry routing information.
        """
        set_id, block_id, path_id = self._parse_season_id(season)

        raw_episodes = get_season_episodes(
            self._http, path_id, block_id, set_id,
        )

        episodes: list[Episode] = []
        for ep in raw_episodes:
            # Encode mpd_id into the episode URL for stream extraction.
            # Format: "episode_url|mpd_id"
            episode_url = ep.url
            if ep.mpd_id:
                episode_url = f"{ep.url}|{ep.mpd_id}"

            episodes.append(
                Episode(
                    number=ep.number,
                    season_number=season.number,
                    title=ep.name,
                    url=episode_url,
                    id=ep.id,
                    duration=ep.duration * 60 if ep.duration else None,
                )
            )

        episodes.sort(key=lambda e: e.number)
        log.info(
            "get_episodes(season %d) -> %d episode(s)",
            season.number,
            len(episodes),
        )
        return episodes

    def get_streams(self, item: Episode | MediaEntry) -> StreamBundle:
        """Resolve HLS/DASH streams for a film or episode.

        For episodes, delegates to :func:`.extractor.extract_streams_from_url`.
        For films, delegates to :func:`.extractor.extract_streams_for_film`.
        """
        if isinstance(item, Episode):
            # Parse the episode URL which may contain "|mpd_id".
            video_url, mpd_id = self._parse_episode_url(item)
            return extract_streams_from_url(
                self._http, video_url, mpd_id=mpd_id,
            )

        # MediaEntry (film) -- use the page URL directly.
        return extract_streams_for_film(self._http, item.url)

    # -- Private helpers ----------------------------------------------------

    @staticmethod
    def _parse_season_id(season: Season) -> tuple[str, str, str]:
        """Extract ``(set_id, block_id, path_id)`` from ``season.id``.

        Raises
        ------
        ValueError
            If the ID is not in the expected encoded format.
        """
        parts = str(season.id).split(":", 2)
        if len(parts) < 3:
            raise ValueError(
                f"Season.id={season.id!r} is not in the expected format "
                f"'set_id:block_id:path_id'.  Ensure get_seasons() was "
                f"called first."
            )
        return parts[0], parts[1], parts[2]

    @staticmethod
    def _parse_episode_url(episode: Episode) -> tuple[str, str]:
        """Extract ``(video_url, mpd_id)`` from an episode URL.

        The URL format is ``"video_url|mpd_id"`` or just ``"video_url"``.
        """
        if "|" in episode.url:
            video_url, mpd_id = episode.url.rsplit("|", 1)
            return video_url, mpd_id
        return episode.url, ""
