"""Shared base class for services on the Aurora platform.

All five Italian Discovery/Warner Bros. Discovery channels -- Real Time,
DMAX, Nove, Food Network, and Home & Garden TV -- share the same Aurora
public API at ``public.aurora.enhanced.live``.  They differ only in the
``filter[environment]`` value that scopes every request.

This module implements the full Aurora workflow exactly once:

1. **Search** -- ``GET /site/search/page/`` with ``filter[environment]``
2. **Seasons / episodes** -- ``GET /site/page/{slug}/`` to fetch blocks
   containing all episodes, then group by ``seasonNumber``
3. **Streams** -- Obtain a bearer token from the homepage ``userMeta``
   realm, then ``POST /playback/v3/videoPlaybackInfo`` to resolve an HLS
   master playlist URL.

Concrete subclasses only set ``name``, ``short_name``, ``environment_id``,
and ``domains`` -- no method overrides are needed.
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
from streamload.services.base import ServiceBase
from streamload.utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AURORA_BASE = "https://public.aurora.enhanced.live"

# The homepage response contains two realm keys.  Content can live on
# either the Aurora ("X-REALM-IT") or legacy Dplay ("X-REALM-DPLAY")
# playback endpoint.  Episodes whose ``channel`` field is ``None`` use
# the Aurora realm; all others use the Dplay realm.
_REALM_IT = "X-REALM-IT"
_REALM_DPLAY = "X-REALM-DPLAY"

_PLAYBACK_ENDPOINT_IT = f"{_AURORA_BASE}/playback/v3/videoPlaybackInfo"
_PLAYBACK_ENDPOINT_DPLAY = (
    "https://eu1-prod.disco-api.com/playback/v3/videoPlaybackInfo"
)

_PAGE_SIZE = 20


class AuroraServiceBase(ServiceBase):
    """Base class for all Aurora-platform streaming services.

    Subclasses must define:

    - **name** -- Display name (e.g. ``"Real Time"``)
    - **short_name** -- Registry key (e.g. ``"rt"``)
    - **environment_id** -- Aurora environment filter (e.g. ``"realtime"``)
    - **domains** -- Known web domains for this channel

    Everything else -- search, season/episode scraping, stream resolution
    -- is implemented here.
    """

    # -- Must be set by each subclass ----------------------------------------
    environment_id: str  # "realtime", "dmaxit", "nove", "foodnetwork", "hgtvit"

    # -- Shared across all Aurora services -----------------------------------
    category = ServiceCategory.SERIE
    language = "it"
    requires_login = False

    # -- Internal caches -----------------------------------------------------

    def __init__(self, http_client):
        super().__init__(http_client)
        # Bearer tokens are fetched lazily and cached for the session
        # lifetime.  Keys: realm name -> {"endpoint": ..., "key": ...}
        self._bearer_cache: dict[str, dict[str, str]] | None = None
        # Show page data is cached between get_seasons() and
        # get_episodes() calls to avoid redundant requests.
        # Key: show_page_url -> list[episode_dict]
        self._episodes_cache: dict[str, list[dict]] = {}

    # -----------------------------------------------------------------------
    # ServiceBase implementation
    # -----------------------------------------------------------------------

    def search(self, query: str) -> list[MediaEntry]:
        """Search the Aurora catalogue for *query*.

        Calls ``GET /site/search/page/`` with the service's environment
        filter.  Only results of type ``showpage`` are returned -- Aurora
        also returns ``videopage`` entries for individual clips, but those
        are not useful for season/episode navigation.
        """
        url = f"{_AURORA_BASE}/site/search/page/"
        params = {
            "include": "default",
            "filter[environment]": self.environment_id,
            "v": "2",
            "q": query,
            "page[number]": "1",
            "page[size]": str(_PAGE_SIZE),
        }

        resp = self._http.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()

        data: list[dict] = payload.get("data") if isinstance(payload, dict) else payload
        if not data:
            log.info("search(%r) -> 0 results on %s", query, self.name)
            return []

        entries: list[MediaEntry] = []
        for item in data:
            if item.get("type") != "showpage":
                continue

            slug = str(item.get("slug", "")).lower().replace(" ", "-")
            parent_slug = item.get("parentSlug", "")

            # Build the show-page URL that get_seasons() will request.
            show_page_url = (
                f"{_AURORA_BASE}/site/page/{slug}/"
                f"?include=default"
                f"&filter[environment]={self.environment_id}"
                f"&v=2"
                f"&parent_slug={parent_slug}"
            )

            year: int | None = None
            date_str = item.get("dateLastModified") or ""
            if date_str and "-" in date_str:
                try:
                    year = int(date_str.split("-")[0])
                except (ValueError, IndexError):
                    pass

            image_url: str | None = None
            image_obj = item.get("image")
            if isinstance(image_obj, dict):
                image_url = image_obj.get("url")

            entries.append(
                MediaEntry(
                    id=str(item.get("id", slug)),
                    title=item.get("title", slug),
                    type=MediaType.SERIE,
                    url=show_page_url,
                    service=self.short_name,
                    year=year,
                    image_url=image_url,
                    description=item.get("description"),
                )
            )

        log.info("search(%r) -> %d result(s) on %s", query, len(entries), self.name)
        return entries

    def get_seasons(self, entry: MediaEntry) -> list[Season]:
        """Fetch seasons for a show :class:`MediaEntry`.

        The Aurora API returns all episodes in a flat list inside the
        show page response (``blocks[1].items``).  We group them by
        ``seasonNumber`` to build the season list, and cache the raw
        episode data so :meth:`get_episodes` doesn't need another request.
        """
        episodes_data = self._fetch_show_episodes(entry.url)

        # Group by season number
        season_numbers: dict[int, int] = {}  # season_num -> episode_count
        for ep in episodes_data:
            sn = ep.get("seasonNumber", 0)
            season_numbers[sn] = season_numbers.get(sn, 0) + 1

        seasons: list[Season] = []
        for num in sorted(season_numbers):
            # Encode the show-page URL into Season.id so get_episodes()
            # can retrieve the cached data without extra state.
            seasons.append(
                Season(
                    number=num,
                    episode_count=season_numbers[num],
                    title=f"Season {num}",
                    id=entry.url,
                )
            )

        log.info(
            "get_seasons(%s) -> %d season(s) on %s",
            entry.title, len(seasons), self.name,
        )
        return seasons

    def get_episodes(self, season: Season) -> list[Episode]:
        """Fetch episodes for a :class:`Season`.

        Uses the cached episode data from the show page (populated by
        :meth:`get_seasons`).  If the cache is cold -- e.g. because the
        caller skipped ``get_seasons`` -- a fresh request is made.
        """
        show_page_url = str(season.id)
        episodes_data = self._fetch_show_episodes(show_page_url)

        # Filter to the requested season
        season_eps = [
            ep for ep in episodes_data
            if ep.get("seasonNumber") == season.number
        ]
        season_eps.sort(key=lambda e: e.get("episodeNumber", 0))

        episodes: list[Episode] = []
        for ep in season_eps:
            ep_number = ep.get("episodeNumber", 0)
            video_id = str(ep.get("id", ""))

            # Duration comes in milliseconds from the API; convert to
            # seconds for the Episode model.
            duration_ms = ep.get("videoDuration", 0)
            duration_secs = round(duration_ms / 1000) if duration_ms else None

            # Determine which playback realm this episode lives on.
            # Episodes with channel=None use the Aurora realm (X-REALM-IT);
            # others use the Dplay realm (X-REALM-DPLAY).
            channel = _REALM_IT if ep.get("channel") is None else _REALM_DPLAY

            # Encode the realm into the URL so get_streams() can use it.
            episode_url = f"aurora://{self.environment_id}/{video_id}?realm={channel}"

            episodes.append(
                Episode(
                    number=ep_number,
                    season_number=season.number,
                    title=ep.get("title", f"Episode {ep_number}"),
                    url=episode_url,
                    id=video_id,
                    duration=duration_secs,
                )
            )

        log.info(
            "get_episodes(S%02d) -> %d episode(s) on %s",
            season.number, len(episodes), self.name,
        )
        return episodes

    def get_streams(self, item: Episode | MediaEntry) -> StreamBundle:
        """Resolve the HLS master playlist for an episode.

        The Aurora playback flow:
        1. Fetch a bearer token from the homepage ``userMeta.realm``.
        2. POST to the realm-specific playback endpoint with the video
           ID to obtain the HLS manifest URL.

        Returns a :class:`StreamBundle` with ``manifest_url`` pointing to
        the HLS master playlist.  Aurora content is not DRM-protected.
        """
        if isinstance(item, Episode):
            video_id = str(item.id)
            realm = self._parse_realm_from_url(item.url)
        else:
            # MediaEntry fallback -- shouldn't occur for serie-only
            # services, but handle gracefully.
            video_id = str(item.id)
            realm = _REALM_IT

        tokens = self._get_bearer_tokens()
        realm_info = tokens.get(realm) or tokens.get(_REALM_IT)
        if realm_info is None:
            log.error("No bearer token found for realm %s on %s", realm, self.name)
            return StreamBundle()

        # POST to the playback endpoint
        playback_resp = self._http.post(
            realm_info["endpoint"],
            headers={"Authorization": f"Bearer {realm_info['key']}"},
            json={
                "deviceInfo": {
                    "adBlocker": False,
                    "drmSupported": True,
                },
                "videoId": video_id,
            },
        )
        playback_resp.raise_for_status()
        playback_data = playback_resp.json()

        # Extract the HLS URL (first streaming entry) from the response.
        streaming_list = (
            playback_data
            .get("data", {})
            .get("attributes", {})
            .get("streaming", [])
        )

        manifest_url: str | None = None
        if streaming_list:
            # Index 0 is HLS, index 1 (if present) is DASH.
            manifest_url = streaming_list[0].get("url")

        log.info(
            "get_streams(%s) -> manifest=%s on %s",
            video_id,
            manifest_url[:80] + "..." if manifest_url and len(manifest_url) > 80 else manifest_url,
            self.name,
        )
        return StreamBundle(manifest_url=manifest_url)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _fetch_show_episodes(self, show_page_url: str) -> list[dict]:
        """Fetch (or return cached) episode data from a show page.

        The Aurora show page response has the structure::

            {
                "blocks": [
                    { ... },            // block 0: hero/metadata
                    { "items": [...] }  // block 1: episode list
                ]
            }

        Each item in ``blocks[1].items`` is an episode dict with fields
        like ``id``, ``title``, ``seasonNumber``, ``episodeNumber``,
        ``videoDuration``, ``channel``, ``show``, etc.
        """
        if show_page_url in self._episodes_cache:
            return self._episodes_cache[show_page_url]

        resp = self._http.get(show_page_url)
        resp.raise_for_status()
        payload = resp.json()

        blocks = payload.get("blocks", [])
        if len(blocks) < 2:
            log.warning(
                "Unexpected Aurora page structure (%d blocks) for %s",
                len(blocks), show_page_url,
            )
            return []

        items: list[dict] = blocks[1].get("items", [])
        self._episodes_cache[show_page_url] = items

        log.debug(
            "Fetched %d episodes from show page: %s",
            len(items), show_page_url[:100],
        )
        return items

    def _get_bearer_tokens(self) -> dict[str, dict[str, str]]:
        """Fetch or return cached bearer tokens from the Aurora homepage.

        The homepage JSON response contains a ``userMeta.realm`` mapping
        with keys like ``X-REALM-IT`` and ``X-REALM-DPLAY``.  Each value
        is a token string used as a Bearer authorization header for the
        corresponding playback endpoint.
        """
        if self._bearer_cache is not None:
            return self._bearer_cache

        homepage_url = (
            f"{_AURORA_BASE}/site/page/homepage/"
            f"?include=default"
            f"&filter[environment]={self.environment_id}"
            f"&v=2"
        )

        resp = self._http.get(homepage_url)
        resp.raise_for_status()
        data = resp.json()

        realm_data = data.get("userMeta", {}).get("realm", {})

        self._bearer_cache = {}
        if _REALM_IT in realm_data:
            self._bearer_cache[_REALM_IT] = {
                "endpoint": _PLAYBACK_ENDPOINT_IT,
                "key": realm_data[_REALM_IT],
            }
        if _REALM_DPLAY in realm_data:
            self._bearer_cache[_REALM_DPLAY] = {
                "endpoint": _PLAYBACK_ENDPOINT_DPLAY,
                "key": realm_data[_REALM_DPLAY],
            }

        log.debug(
            "Obtained bearer tokens for realms: %s",
            list(self._bearer_cache.keys()),
        )
        return self._bearer_cache

    @staticmethod
    def _parse_realm_from_url(url: str) -> str:
        """Extract the realm name from an ``aurora://`` episode URL.

        URL format: ``aurora://{env}/{video_id}?realm={realm_key}``
        Falls back to ``X-REALM-IT`` when the URL is not in the expected
        format.
        """
        if "realm=" in url:
            return url.split("realm=")[-1].split("&")[0]
        return _REALM_IT
