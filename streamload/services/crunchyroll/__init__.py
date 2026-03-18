"""Crunchyroll service plugin for Streamload.

Crunchyroll is the world's largest anime streaming platform, offering
subtitled and dubbed anime in multiple languages.  Access requires
authentication via a ``device_id`` and ``etp_rt`` session cookie.

Search uses the REST ``/content/v2/discover/search`` API.  Season and
episode metadata comes from the CMS v2 API.  Streams are DASH (MPD)
with Widevine DRM, resolved through the ``cr-play-service``.

Registration::

    @ServiceRegistry.register
    class CrunchyrollService(ServiceBase): ...
"""

from __future__ import annotations

import base64
import json
import time

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
    get_season_episodes,
    get_series_seasons,
    search_titles,
)

log = get_logger(__name__)

_BASE_URL = "https://www.crunchyroll.com"
_API_BASE_URL = "https://beta-api.crunchyroll.com"
_PUBLIC_TOKEN = "bm9haWhkZXZtXzZpeWcwYThsMHE6"


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------

def _jwt_exp(token: str | None) -> int | None:
    """Extract the expiration timestamp from a JWT token."""
    if not isinstance(token, str) or token.count(".") < 2:
        return None
    try:
        payload_b64 = token.split(".", 2)[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload = base64.urlsafe_b64decode(payload_b64 + padding).decode(
            "utf-8", errors="replace"
        )
        obj = json.loads(payload)
        exp = obj.get("exp")
        if isinstance(exp, int):
            return exp
        if isinstance(exp, str) and exp.isdigit():
            return int(exp)
    except Exception:
        pass
    return None


class _CrunchyrollAuth:
    """Manages Crunchyroll authentication state.

    Handles the ``etp_rt`` cookie-based token exchange, access token
    refresh, and session lifecycle.
    """

    def __init__(
        self,
        http: HttpClient,
        device_id: str,
        etp_rt: str,
        locale: str = "it-IT",
    ) -> None:
        self._http = http
        self.device_id = device_id
        self.etp_rt = etp_rt
        self.locale = locale

        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.account_id: str | None = None
        self.expires_at: float = 0.0

    @property
    def _api_headers(self) -> dict[str, str]:
        """Base headers for Crunchyroll API requests."""
        headers = {
            "accept": "application/json, text/plain, */*",
            "origin": _BASE_URL,
            "referer": f"{_BASE_URL}/",
            "accept-language": f"{self.locale.replace('_', '-')},en-US;q=0.8,en;q=0.7",
        }
        if self.access_token:
            headers["authorization"] = f"Bearer {self.access_token}"
        return headers

    @property
    def _cookies(self) -> dict[str, str]:
        """Cookies for API requests."""
        cookies = {"device_id": self.device_id}
        if self.etp_rt:
            cookies["etp_rt"] = self.etp_rt
        return cookies

    def authenticate(self) -> bool:
        """Authenticate using the etp_rt cookie.

        Returns
        -------
        bool
            ``True`` on success, ``False`` on failure.
        """
        headers = self._api_headers
        headers["authorization"] = f"Basic {_PUBLIC_TOKEN}"
        headers["content-type"] = "application/x-www-form-urlencoded"

        # Use form-encoded data for the token endpoint.
        form_data = {
            "device_id": self.device_id,
            "device_type": "Chrome on Windows",
            "grant_type": "etp_rt_cookie",
        }

        log.debug("Authenticating with Crunchyroll")
        resp = self._http.post(
            f"{_API_BASE_URL}/auth/v1/token",
            headers=headers,
            data=form_data,
        )

        if resp.status_code != 200:
            log.error(
                "Crunchyroll authentication failed: HTTP %d",
                resp.status_code,
            )
            return False

        result = resp.json()
        self.access_token = result.get("access_token")
        self.refresh_token = result.get("refresh_token")
        self.account_id = result.get("account_id")

        expires_in = int(result.get("expires_in", 3600) or 3600)
        self._set_expires_at(expires_in=expires_in)

        log.info("Crunchyroll authenticated as account=%s", self.account_id)
        return True

    def _refresh(self) -> bool:
        """Refresh the access token using the refresh token.

        Returns
        -------
        bool
            ``True`` on success.
        """
        if not self.refresh_token:
            return False

        headers = self._api_headers
        headers["authorization"] = f"Basic {_PUBLIC_TOKEN}"
        headers["content-type"] = "application/x-www-form-urlencoded"

        form_data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "device_type": "Chrome on Windows",
            "device_id": self.device_id,
        }

        resp = self._http.post(
            f"{_API_BASE_URL}/auth/v1/token",
            headers=headers,
            data=form_data,
        )

        if resp.status_code != 200:
            log.warning("Token refresh failed: %d", resp.status_code)
            return False

        result = resp.json()
        self.access_token = result.get("access_token")
        new_refresh = result.get("refresh_token")
        if new_refresh:
            self.refresh_token = new_refresh

        expires_in = int(result.get("expires_in", 3600) or 3600)
        self._set_expires_at(expires_in=expires_in)
        return True

    def ensure_token(self) -> None:
        """Ensure a valid access token is available.

        Refreshes or re-authenticates as needed.

        Raises
        ------
        AuthenticationError
            If authentication cannot be established.
        """
        if not self.access_token:
            if not self.authenticate():
                raise AuthenticationError(
                    "Initial authentication failed",
                    service_name="crunchyroll",
                )
            return

        if time.time() >= (self.expires_at - 30):
            if not self._refresh():
                if not self.authenticate():
                    raise AuthenticationError(
                        "Re-authentication failed",
                        service_name="crunchyroll",
                    )

    def _set_expires_at(self, *, expires_in: int | None = None) -> None:
        """Set token expiration from JWT or expires_in."""
        exp = _jwt_exp(self.access_token)
        if isinstance(exp, int) and exp > 0:
            self.expires_at = float(exp - 60)
            return
        if expires_in is not None:
            self.expires_at = time.time() + max(0, expires_in - 60)
        else:
            self.expires_at = 0.0


# ---------------------------------------------------------------------------
# Service implementation
# ---------------------------------------------------------------------------

@ServiceRegistry.register
class CrunchyrollService(ServiceBase):
    """Crunchyroll (www.crunchyroll.com) service plugin.

    Supports searching, browsing seasons/episodes, and resolving
    DASH streams with Widevine DRM for anime content.

    Requires authentication credentials:

    - ``device_id``: Browser device UUID from cookies.
    - ``etp_rt``: Session token from the ``etp_rt`` cookie.
    """

    name = "Crunchyroll"
    short_name = "cr"
    domains = ["www.crunchyroll.com"]
    category = ServiceCategory.ANIME
    language = "multi"
    requires_login = True

    def __init__(self, http_client: HttpClient) -> None:
        super().__init__(http_client)
        self._auth: _CrunchyrollAuth | None = None
        self._locale = "it-IT"

    # -- Authentication -----------------------------------------------------

    def authenticate(self, credentials: dict[str, str]) -> AuthSession | None:
        """Authenticate with Crunchyroll.

        Parameters
        ----------
        credentials:
            Must contain ``"device_id"`` and ``"etp_rt"`` keys.

        Returns
        -------
        AuthSession | None
            A populated session on success, ``None`` on failure.
        """
        device_id = credentials.get("device_id", "")
        etp_rt = credentials.get("etp_rt", "")

        if not device_id or not etp_rt:
            log.error("Missing device_id or etp_rt in credentials")
            return None

        self._auth = _CrunchyrollAuth(
            self._http, device_id, etp_rt, self._locale,
        )

        if not self._auth.authenticate():
            self._auth = None
            return None

        session = AuthSession(
            cookies={"device_id": device_id, "etp_rt": etp_rt},
            headers={"authorization": f"Bearer {self._auth.access_token}"},
            expires_at=self._auth.expires_at,
        )
        self._session = session
        return session

    def _ensure_auth(self) -> _CrunchyrollAuth:
        """Ensure authentication is established.

        Raises
        ------
        AuthenticationError
            If not authenticated.
        """
        if self._auth is None:
            raise AuthenticationError(
                "Not authenticated -- call authenticate() with "
                "device_id and etp_rt first",
                service_name="crunchyroll",
            )
        self._auth.ensure_token()
        return self._auth

    # -- ServiceBase interface ----------------------------------------------

    def search(self, query: str) -> list[MediaEntry]:
        """Search Crunchyroll via the discover/search REST API."""
        auth = self._ensure_auth()

        raw_titles = search_titles(
            self._http,
            query,
            auth.access_token,
            locale=self._locale,
        )

        entries: list[MediaEntry] = []
        for t in raw_titles:
            media_type = MediaType.ANIME

            entries.append(
                MediaEntry(
                    id=t.id,
                    title=t.name,
                    type=media_type,
                    url=t.url,
                    service=self.short_name,
                    image_url=t.image_url,
                )
            )

        log.info("search(%r) -> %d entries", query, len(entries))
        return entries

    def get_seasons(self, entry: MediaEntry) -> list[Season]:
        """Fetch seasons via the CMS v2 API."""
        auth = self._ensure_auth()

        series_id = entry.id
        series_name, raw_seasons = get_series_seasons(
            self._http,
            series_id,
            auth.access_token,
            locale=self._locale,
        )

        if not raw_seasons:
            return []

        seasons: list[Season] = []
        for rs in raw_seasons:
            # Encode routing info: "season_api_id:series_id"
            encoded_id = f"{rs.id}:{series_id}"

            seasons.append(
                Season(
                    number=rs.number,
                    id=encoded_id,
                    title=rs.title,
                )
            )

        seasons.sort(key=lambda s: s.number)
        log.info("get_seasons(%s) -> %d season(s)", entry.id, len(seasons))
        return seasons

    def get_episodes(self, season: Season) -> list[Episode]:
        """Fetch episodes via the CMS v2 API."""
        auth = self._ensure_auth()
        season_api_id, series_id = self._parse_season_id(season)

        raw_episodes = get_season_episodes(
            self._http,
            season_api_id,
            auth.access_token,
            locale=self._locale,
        )

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
        For films/movies, uses the MediaEntry GUID (``item.id``).
        """
        auth = self._ensure_auth()

        media_id = item.id if isinstance(item, Episode) else item.id
        if not media_id:
            raise ServiceError(
                "No media ID available for stream resolution",
                service_name="crunchyroll",
            )

        # For episodes accessed via URL, extract the ID from the URL path.
        if "/" in media_id:
            media_id = media_id.rsplit("/", 1)[-1]

        return extract_streams(
            self._http,
            media_id,
            auth.access_token,
            locale=self._locale,
        )

    # -- Private helpers ----------------------------------------------------

    @staticmethod
    def _parse_season_id(season: Season) -> tuple[str, str]:
        """Extract ``(season_api_id, series_id)`` from ``season.id``.

        Raises
        ------
        ValueError
            If the ID is not in the expected encoded format.
        """
        parts = str(season.id).split(":", 1)
        if len(parts) < 2:
            raise ValueError(
                f"Season.id={season.id!r} is not in the expected format "
                f"'season_api_id:series_id'.  Ensure get_seasons() was "
                f"called first."
            )
        return parts[0], parts[1]
