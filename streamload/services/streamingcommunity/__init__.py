"""StreamingCommunity service plugin for Streamload.

StreamingCommunity is the most popular Italian streaming aggregator for
films and TV series.  It uses an Inertia.js frontend with a VixCloud-based
video player.  Content is available in both Italian and English.

Registration::

    @ServiceRegistry.register
    class StreamingCommunityService(ServiceBase): ...

The service is automatically discovered by :func:`streamload.services.load_services`
when it imports the ``streamload.services.streamingcommunity`` package.
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
from .scraper import get_season_episodes, get_title_seasons, search_titles

log = get_logger(__name__)


def _media_type_from_api(type_str: str) -> MediaType:
    """Map the StreamingCommunity API type string to :class:`MediaType`."""
    if type_str in ("tv", "tvshow"):
        return MediaType.SERIE
    return MediaType.FILM


@ServiceRegistry.register
class StreamingCommunityService(ServiceBase):
    """StreamingCommunity (streamingcommunity.prof) service plugin.

    Supports searching, browsing seasons/episodes, and resolving HLS
    streams for both films and TV series.
    """

    name = "StreamingCommunity"
    short_name = "sc"
    domains = ["streamingcommunityz.bargains", "streamingcommunityz.nl", "streamingcommunityz.pet"]
    category = ServiceCategory.FILM_SERIE
    language = "it"
    requires_login = False

    # Discovery seeds: when all higher-priority sources fail, the resolver
    # permutes prefix x tld and probes each. The active validator filters
    # parking pages, so the broad TLD list is safe.
    discovery = {
        "prefixes": ["streamingcommunityz", "streamingcommunity"],
        "tlds": [
            # Currently or recently in rotation
            "bargains", "pet", "nl", "prof", "computer",
            # Common cheap TLDs used for streaming rotation
            "skin", "shopping", "online", "life", "ws", "best", "vip",
            "cyou", "icu", "zone", "live", "watch", "quest", "monster",
            "click", "rest", "tv", "fun", "bid", "fyi", "cfd", "buzz",
            "lol", "wtf", "boats", "homes", "boo", "rip", "men",
        ],
    }

    # -- Internal state cached between get_seasons / get_episodes calls ----

    def __init__(self, http_client):
        super().__init__(http_client)
        # Cache the Inertia version obtained during get_seasons() so that
        # get_episodes() can reuse it without an extra round-trip.
        self._inertia_version_cache: dict[str, str] = {}

    # -- ServiceBase interface ----------------------------------------------

    def search(self, query: str) -> list[MediaEntry]:
        """Search StreamingCommunity across IT and EN catalogues.

        Returns de-duplicated :class:`MediaEntry` results.
        """
        raw_titles = search_titles(self._http, self.base_url, query)

        entries: list[MediaEntry] = []
        for t in raw_titles:
            media_type = _media_type_from_api(t.type)
            # Build a canonical URL for display / identification.
            title_url = f"{self.base_url}/{t.language}/titles/{t.id}-{t.slug}"

            year_int: int | None = None
            if t.year is not None:
                try:
                    year_int = int(t.year)
                except (ValueError, TypeError):
                    year_int = None

            entries.append(
                MediaEntry(
                    id=str(t.id),
                    title=t.name,
                    type=media_type,
                    url=title_url,
                    service=self.short_name,
                    year=year_int,
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

        media_id, slug, lang = self._parse_entry(entry)
        version, seasons_data = get_title_seasons(
            self._http, self.base_url, media_id, slug, lang,
        )

        # Cache the version so get_episodes() can skip the title page.
        cache_key = f"{media_id}:{slug}:{lang}"
        self._inertia_version_cache[cache_key] = version

        seasons: list[Season] = []
        for s in seasons_data:
            native_id = s.get("id", "")
            # Encode routing info into Season.id so that get_episodes()
            # can recover media_id, slug, and lang without extra state.
            # Format: "{native_season_id}:{media_id}:{slug}:{lang}"
            encoded_id = f"{native_id}:{media_id}:{slug}:{lang}"
            seasons.append(
                Season(
                    number=s.get("number", 0),
                    id=encoded_id,
                    title=f"Season {s.get('number', '?')}",
                    episode_count=s.get("episodes_count", 0),
                )
            )

        seasons.sort(key=lambda s: s.number)
        log.info("get_seasons(%s) -> %d season(s)", entry.id, len(seasons))
        return seasons

    def get_episodes(self, season: Season) -> list[Episode]:
        """Fetch episodes for a :class:`Season`.

        Requires that :meth:`get_seasons` was called first so the
        Inertia version is cached.  The ``season.id`` is expected to
        encode ``media_id:slug:lang:season_number`` (see
        :meth:`get_seasons`).
        """
        media_id, slug, lang, season_number = self._parse_season(season)

        cache_key = f"{media_id}:{slug}:{lang}"
        inertia_version = self._inertia_version_cache.get(cache_key)
        if inertia_version is None:
            # Fall back to fetching the title page for the version.
            inertia_version, _ = get_title_seasons(
                self._http, self.base_url, media_id, slug, lang,
            )
            self._inertia_version_cache[cache_key] = inertia_version

        episodes_data = get_season_episodes(
            self._http,
            self.base_url,
            media_id,
            slug,
            season_number,
            inertia_version,
            lang,
        )

        episodes: list[Episode] = []
        for ep in episodes_data:
            ep_number = ep.get("number", 0)
            ep_name = ep.get("name") or f"Episode {ep_number}"
            ep_url = (
                f"{self.base_url}/{lang}/titles/{media_id}-{slug}"
                f"/season-{season_number}"
            )

            episodes.append(
                Episode(
                    number=ep_number,
                    season_number=season_number,
                    title=ep_name,
                    url=ep_url,
                    id=str(ep.get("id", "")),
                    duration=ep.get("duration"),
                )
            )

        episodes.sort(key=lambda e: e.number)
        log.info(
            "get_episodes(season %d) -> %d episode(s)",
            season_number,
            len(episodes),
        )
        return episodes

    def get_streams(self, item: Episode | MediaEntry) -> StreamBundle:
        """Resolve HLS streams for a film or episode.

        Delegates to :mod:`.extractor` which in turn uses the
        :mod:`streamload.player.vixcloud` module.
        """
        if isinstance(item, Episode):
            media_id, slug, lang, _ = self._parse_episode(item)
            episode_id = int(item.id) if item.id else None
            service_url = f"{self.base_url}/{lang}"

            return extract_streams(
                self._http,
                service_url,
                media_id,
                episode_id=episode_id,
            )

        # MediaEntry (film)
        media_id, slug, lang = self._parse_entry(item)
        service_url = f"{self.base_url}/{lang}"

        return extract_streams(
            self._http,
            service_url,
            media_id,
        )

    # -- Private helpers ----------------------------------------------------

    @staticmethod
    def _parse_entry(entry: MediaEntry) -> tuple[int, str, str]:
        """Extract ``(media_id, slug, lang)`` from a :class:`MediaEntry`.

        The URL format is::

            https://streamingcommunity.prof/{lang}/titles/{id}-{slug}

        Returns
        -------
        tuple[int, str, str]
            ``(media_id, slug, language_code)``
        """
        # entry.url example:
        #   https://streamingcommunity.prof/it/titles/123-some-slug
        parts = entry.url.rstrip("/").split("/")
        # parts[-1] = "123-some-slug"
        # parts[-3] = "it" (language)
        id_slug = parts[-1]
        lang = parts[-3] if len(parts) >= 4 else "it"

        dash_idx = id_slug.index("-") if "-" in id_slug else len(id_slug)
        media_id = int(id_slug[:dash_idx])
        slug = id_slug[dash_idx + 1:] if "-" in id_slug else ""

        return media_id, slug, lang

    @staticmethod
    def _parse_season(season: Season) -> tuple[int, str, str, int]:
        """Extract routing info from a :class:`Season`.

        The ``Season.id`` is encoded by :meth:`get_seasons` as
        ``"{native_season_id}:{media_id}:{slug}:{lang}"`` so that
        :meth:`get_episodes` can recover the title routing parameters
        without maintaining external state.

        Returns
        -------
        tuple[int, str, str, int]
            ``(media_id, slug, lang, season_number)``

        Raises
        ------
        ValueError
            If ``season.id`` is not in the expected encoded format.
        """
        parts = str(season.id).split(":")
        if len(parts) >= 4:
            _native_id, media_id_str, slug, lang = parts[0], parts[1], parts[2], parts[3]
            return int(media_id_str), slug, lang, season.number
        raise ValueError(
            f"Season.id={season.id!r} is not in the expected encoded "
            f"format 'native_id:media_id:slug:lang'.  Ensure get_seasons() "
            f"was called first."
        )

    @staticmethod
    def _parse_episode(episode: Episode) -> tuple[int, str, str, int]:
        """Extract routing info from an :class:`Episode`.

        The episode URL follows the pattern::

            https://streamingcommunity.prof/{lang}/titles/{id}-{slug}/season-{n}

        Returns ``(media_id, slug, lang, season_number)``.
        """
        parts = episode.url.rstrip("/").split("/")
        # parts[-1] = "season-3"
        # parts[-2] = "123-some-slug"
        # parts[-4] = "it"
        season_str = parts[-1]  # "season-3"
        season_number = int(season_str.split("-")[-1]) if "-" in season_str else episode.season_number

        id_slug = parts[-2]  # "123-some-slug"
        lang = parts[-4] if len(parts) >= 5 else "it"

        dash_idx = id_slug.index("-") if "-" in id_slug else len(id_slug)
        media_id = int(id_slug[:dash_idx])
        slug = id_slug[dash_idx + 1:] if "-" in id_slug else ""

        return media_id, slug, lang, season_number
