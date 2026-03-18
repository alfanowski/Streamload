"""Mediaset Infinity service plugin for Streamload.

Mediaset Infinity is the streaming platform of Mediaset (Italy's largest
commercial broadcaster), offering films, TV series, reality shows, and
live broadcasts.  Free content is accessible without login; premium
(Infinity+) content requires a subscription.

Search uses the GraphQL persisted-query API with SHA256 hashes scraped
from the frontend JavaScript.  Authentication is handled via anonymous
or subscription bearer tokens.  Streams are DASH (MPD) with
PlayReady/Widevine DRM.

Registration::

    @ServiceRegistry.register
    class MediasetInfinityService(ServiceBase): ...
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid

from bs4 import BeautifulSoup

from streamload.core.exceptions import AuthenticationError, ServiceError
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
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

from .extractor import extract_streams
from .scraper import (
    RawSeason,
    get_season_episodes,
    get_series_seasons,
    search_titles_with_api,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Anonymous authentication and SHA256 hash discovery
# ---------------------------------------------------------------------------

_ANON_LOGIN_URL = (
    "https://api-ott-prod-fe.mediaset.net/PROD/play/idm/anonymous/login/v2.0"
)


def _decode_jwt_payload(token: str) -> dict:
    """Decode a JWT payload without signature verification."""
    try:
        part = token.split(".")[1]
        part += "=" * (4 - len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except (IndexError, ValueError, json.JSONDecodeError):
        return {}


def _is_token_valid(token: str) -> bool:
    """Check if a JWT token is still valid (5-minute buffer)."""
    payload = _decode_jwt_payload(token)
    exp = payload.get("exp", 0)
    return exp > time.time() + 300


class _MediasetAPIState:
    """Internal state for the Mediaset API authentication.

    Manages the anonymous bearer token, client ID, app name, and the
    SHA256 hash for the persisted GraphQL search query.
    """

    def __init__(self) -> None:
        self.client_id: str = str(uuid.uuid4())
        self.app_name: str = ""
        self.be_token: str = ""
        self.account_id: str = ""
        self.sha256_hash: str = ""

    def initialize(self, http: HttpClient) -> None:
        """Bootstrap the API state: fetch app name, token, hash.

        Parameters
        ----------
        http:
            Shared HTTP client.

        Raises
        ------
        ServiceError
            If any step fails.
        """
        # Step 1: Fetch the homepage to extract the app-name meta tag.
        log.debug("Fetching Mediaset homepage for app-name")
        resp = http.get(
            "https://mediasetinfinity.mediaset.it/",
            use_curl=True,
        )
        resp.raise_for_status()
        html = resp.text

        soup = BeautifulSoup(html, "html.parser")
        meta = soup.find("meta", attrs={"name": "app-name"})
        if meta:
            self.app_name = meta.get("content", "")

        if not self.app_name:
            raise ServiceError(
                "Could not extract app-name from Mediaset homepage",
                service_name="mediasetinfinity",
            )

        # Step 2: Generate anonymous bearer token.
        self._generate_token(http)

        # Step 3: Extract SHA256 hash from frontend JavaScript.
        self._extract_hash(html)

    def _generate_token(self, http: HttpClient) -> None:
        """Generate an anonymous bearer token."""
        json_body = {
            "appName": self.app_name,
            "client_id": self.client_id,
        }
        resp = http.post(_ANON_LOGIN_URL, json=json_body)
        resp.raise_for_status()
        data = resp.json()

        self.be_token = data.get("response", {}).get("beToken", "")
        if not self.be_token:
            raise ServiceError(
                "Failed to obtain anonymous bearer token",
                service_name="mediasetinfinity",
            )

        self.account_id = _decode_jwt_payload(self.be_token).get("oid", "")
        log.debug("Obtained anonymous token, account_id=%s", self.account_id)

    def _extract_hash(self, html: str) -> None:
        """Extract the SHA256 hash for the persisted search query.

        The hash is embedded in the frontend JavaScript bundles. We
        find all inline scripts containing ``imageEngines`` and parse
        the SHA256 hash / variable pairs.
        """
        soup = BeautifulSoup(html, "html.parser")
        scripts = [
            s.get_text()
            for s in soup.find_all("script")
            if "imageEngines" in s.get_text()
        ]

        if not scripts:
            raise ServiceError(
                "Could not find script containing imageEngines",
                service_name="mediasetinfinity",
            )

        try:
            relevant = (
                scripts[0]
                .replace('\\"', "")
                .split("...Option")[1]
                .split("imageEngines")[0]
            )
            pairs: dict[str, str] = {}
            for match in re.finditer(r"([a-f0-9]{64}):\$(\w+)", relevant):
                pairs[match.group(1)] = f"${match.group(2)}"

            if not pairs:
                raise ServiceError(
                    "No SHA256 hash pairs found in script",
                    service_name="mediasetinfinity",
                )

            # The search hash is typically the 5th from the end.
            self.sha256_hash = list(pairs.keys())[-5]
            log.debug("Extracted SHA256 hash: %s", self.sha256_hash[:16])

        except (IndexError, KeyError) as exc:
            raise ServiceError(
                f"Failed to parse SHA256 hash from script: {exc}",
                service_name="mediasetinfinity",
            ) from exc

    def ensure_valid_token(self, http: HttpClient) -> None:
        """Ensure the bearer token is still valid, refreshing if needed."""
        if not self.be_token or not _is_token_valid(self.be_token):
            log.info("Bearer token expired, refreshing")
            self._generate_token(http)

    @property
    def request_headers(self) -> dict[str, str]:
        """Generate HTTP headers for Mediaset API requests."""
        return {
            "authorization": self.be_token,
            "x-m-device-id": self.client_id,
            "x-m-platform": "WEB",
            "x-m-property": "MPLAY",
            "x-m-sid": self.client_id,
        }


# ---------------------------------------------------------------------------
# Service implementation
# ---------------------------------------------------------------------------

@ServiceRegistry.register
class MediasetInfinityService(ServiceBase):
    """Mediaset Infinity (mediasetinfinity.mediaset.it) service plugin.

    Supports searching, browsing seasons/episodes, and resolving
    DASH streams with Widevine DRM for both films and TV series.
    """

    name = "Mediaset Infinity"
    short_name = "mi"
    domains = ["mediasetinfinity.mediaset.it"]
    category = ServiceCategory.FILM_SERIE
    language = "it"
    requires_login = False

    def __init__(self, http_client: HttpClient) -> None:
        super().__init__(http_client)
        self._api = _MediasetAPIState()
        self._initialized = False
        # Cache seasons data for get_episodes calls.
        self._seasons_cache: dict[str, list[RawSeason]] = {}

    def _ensure_initialized(self) -> None:
        """Lazy-initialize the API state on first use."""
        if self._initialized:
            self._api.ensure_valid_token(self._http)
            return

        self._api.initialize(self._http)
        self._initialized = True

    # -- ServiceBase interface ----------------------------------------------

    def search(self, query: str) -> list[MediaEntry]:
        """Search Mediaset Infinity via the GraphQL persisted-query API."""
        self._ensure_initialized()

        raw_titles = search_titles_with_api(
            self._http,
            query,
            self._api.sha256_hash,
            self._api.request_headers,
        )

        entries: list[MediaEntry] = []
        for t in raw_titles:
            media_type = MediaType.SERIE if t.type == "tv" else MediaType.FILM

            year_int: int | None = None
            if t.year:
                try:
                    year_int = int(t.year)
                except (ValueError, TypeError):
                    year_int = None

            entries.append(
                MediaEntry(
                    id=t.id,
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
        """Fetch seasons from the Mediaset series API."""
        if entry.type == MediaType.FILM:
            return []

        series_name, raw_seasons = get_series_seasons(
            self._http, entry.url,
        )

        if not raw_seasons:
            log.info("No seasons found for %s", entry.url)
            return []

        # Cache for get_episodes.
        cache_key = entry.id
        self._seasons_cache[cache_key] = raw_seasons

        seasons: list[Season] = []
        for rs in raw_seasons:
            # Encode routing info: "guid:season_url:entry_id"
            encoded_id = f"{rs.guid}:{rs.url or rs.id}:{entry.id}"

            seasons.append(
                Season(
                    number=rs.number,
                    id=encoded_id,
                    title=rs.title or f"Season {rs.number}",
                )
            )

        seasons.sort(key=lambda s: s.number)
        log.info("get_seasons(%s) -> %d season(s)", entry.id, len(seasons))
        return seasons

    def get_episodes(self, season: Season) -> list[Episode]:
        """Fetch episodes for a season from the programs feed."""
        guid, season_url, entry_id = self._parse_season_id(season)

        # Look up the full RawSeason from cache.
        raw_seasons = self._seasons_cache.get(entry_id, [])
        raw_season = next(
            (rs for rs in raw_seasons if rs.guid == guid),
            None,
        )

        if not raw_season:
            # Reconstruct a minimal RawSeason.
            raw_season = RawSeason(
                number=season.number,
                title=season.title or "",
                id=season_url.rsplit("/", 1)[-1] if "/" in season_url else season_url,
                guid=guid,
                url=season_url,
            )

        raw_episodes = get_season_episodes(self._http, raw_season)

        episodes: list[Episode] = []
        for ep in raw_episodes:
            episodes.append(
                Episode(
                    number=ep.number,
                    season_number=season.number,
                    title=ep.name,
                    url=ep.url,
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
        """Resolve DASH streams with Widevine DRM.

        For episodes, uses the episode GUID (``item.id``).
        For films, uses the MediaEntry GUID (``item.id``).
        """
        self._ensure_initialized()

        content_id = item.id if isinstance(item, Episode) else item.id
        if not content_id:
            raise ServiceError(
                "No content ID available for stream resolution",
                service_name="mediasetinfinity",
            )

        return extract_streams(
            self._http,
            content_id,
            self._api.be_token,
            self._api.account_id,
        )

    # -- Private helpers ----------------------------------------------------

    @staticmethod
    def _parse_season_id(season: Season) -> tuple[str, str, str]:
        """Extract ``(guid, season_url, entry_id)`` from ``season.id``.

        Raises
        ------
        ValueError
            If the ID is not in the expected format.
        """
        parts = str(season.id).split(":", 2)
        if len(parts) < 3:
            raise ValueError(
                f"Season.id={season.id!r} is not in the expected format "
                f"'guid:season_url:entry_id'.  Ensure get_seasons() was "
                f"called first."
            )
        return parts[0], parts[1], parts[2]
