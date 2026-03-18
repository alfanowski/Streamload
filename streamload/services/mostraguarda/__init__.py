"""MostraGuarda service plugin for Streamload.

MostraGuarda is an Italian film-only streaming service.  It uses TMDB
for search (since it has no native search API) and resolves films by
their IMDB ID to SuperVideo embeds for HLS playback.

Since this is a film-only service, ``get_seasons()`` and
``get_episodes()`` always return empty lists.

Registration::

    @ServiceRegistry.register
    class MostraGuardaService(ServiceBase): ...

The service is automatically discovered by
:func:`streamload.services.load_services` when it imports the
``streamload.services.mostraguarda`` package.
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
from streamload.utils.tmdb import TMDBClient

from .extractor import extract_streams
from .scraper import resolve_player_url

log = get_logger(__name__)

# TMDB API key -- same key used across the application.
# In production this would come from AppConfig; we use a well-known
# community key as a fallback.
_TMDB_API_KEY = "a800ed6c93274fb857ea61bd9e246a9c"


@ServiceRegistry.register
class MostraGuardaService(ServiceBase):
    """MostraGuarda (mostraguarda.uno) service plugin.

    Film-only service.  Search is powered by TMDB; film resolution uses
    the IMDB ID to look up SuperVideo embeds on mostraguarda.stream.
    """

    name = "MostraGuarda"
    short_name = "mg"
    domains = ["mostraguarda.uno"]
    category = ServiceCategory.FILM
    language = "it"
    requires_login = False

    def __init__(self, http_client):
        super().__init__(http_client)
        self._tmdb = TMDBClient(api_key=_TMDB_API_KEY, http_client=http_client)

    # -- ServiceBase interface ----------------------------------------------

    def search(self, query: str) -> list[MediaEntry]:
        """Search for films using TMDB.

        Returns :class:`MediaEntry` results enriched with TMDB metadata.
        Each entry carries the IMDB ID (when available) in the ``url``
        field for later resolution via :meth:`get_streams`.
        """
        if not self._tmdb.enabled:
            log.warning("TMDB API key not configured; MostraGuarda search disabled")
            return []

        # Use TMDB movie search.
        params = {"query": query, "language": "it-IT"}
        data = self._tmdb._get("/search/movie", params=params)
        if data is None:
            return []

        results_list = data.get("results") or []
        entries: list[MediaEntry] = []

        for movie in results_list[:20]:
            title = movie.get("title", "")
            movie_id = movie.get("id", 0)

            # Extract year.
            year: int | None = None
            release_date = movie.get("release_date", "")
            if release_date and len(release_date) >= 4:
                try:
                    year = int(release_date[:4])
                except ValueError:
                    pass

            # Poster image.
            poster_path = movie.get("poster_path", "")
            image_url = (
                f"{TMDBClient.IMAGE_BASE}{poster_path}" if poster_path else None
            )

            # Description.
            description = movie.get("overview") or None

            # Genre.
            genre_ids = movie.get("genre_ids") or []
            genre_names = [
                TMDBClient.MOVIE_GENRES[gid]
                for gid in genre_ids
                if gid in TMDBClient.MOVIE_GENRES
            ]
            genre = genre_names[0] if genre_names else None

            # We need the IMDB ID for resolution.  TMDB search doesn't
            # return it directly; we'll fetch it on demand in get_streams().
            # Store the TMDB movie ID in the entry ID and URL.
            entries.append(
                MediaEntry(
                    id=str(movie_id),
                    title=title,
                    type=MediaType.FILM,
                    url=str(movie_id),  # TMDB movie ID
                    service=self.short_name,
                    year=year,
                    genre=genre,
                    image_url=image_url,
                    description=description,
                )
            )

        log.info("search(%r) -> %d entries", query, len(entries))
        return entries

    def get_seasons(self, entry: MediaEntry) -> list[Season]:
        """Film-only service -- always returns an empty list."""
        return []

    def get_episodes(self, season: Season) -> list[Episode]:
        """Film-only service -- always returns an empty list."""
        return []

    def get_streams(self, item: Episode | MediaEntry) -> StreamBundle:
        """Resolve HLS streams for a film.

        Fetches the IMDB ID from TMDB, then resolves the SuperVideo
        embed URL from MostraGuarda, and finally extracts the HLS
        playlist.

        Delegates to :mod:`.extractor` which in turn uses the
        :mod:`streamload.player.supervideo` module.
        """
        if isinstance(item, Episode):
            from streamload.core.exceptions import ServiceError
            raise ServiceError(
                "MostraGuarda is a film-only service",
                service_name="mostraguarda",
            )

        tmdb_id = item.id
        imdb_id = self._get_imdb_id(tmdb_id)
        if not imdb_id:
            from streamload.core.exceptions import ServiceError
            raise ServiceError(
                f"Could not obtain IMDB ID for {item.title} (TMDB {tmdb_id})",
                service_name="mostraguarda",
            )

        player_url = resolve_player_url(self._http, imdb_id)
        if not player_url:
            from streamload.core.exceptions import ServiceError
            raise ServiceError(
                f"Film not found on MostraGuarda: {item.title} ({imdb_id})",
                service_name="mostraguarda",
            )

        return extract_streams(self._http, player_url)

    # -- Private helpers ----------------------------------------------------

    def _get_imdb_id(self, tmdb_id: str) -> str | None:
        """Fetch the IMDB ID for a TMDB movie ID.

        Calls TMDB ``/movie/{id}/external_ids`` to obtain the IMDB ID.
        """
        data = self._tmdb._get(f"/movie/{tmdb_id}/external_ids")
        if data is None:
            return None

        imdb_id = data.get("imdb_id")
        if imdb_id:
            log.debug("TMDB %s -> IMDB %s", tmdb_id, imdb_id)
        return imdb_id
