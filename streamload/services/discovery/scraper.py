"""Web scraping logic for Discovery+.

Handles search and metadata extraction from Discovery+.  The service
uses a CMS API that returns JSON:API-style responses.

Search: ``/cms/routes/search/result`` with ``contentFilter[query]``
parameter -- returns ``included[]`` objects of type ``show`` and
``video``, plus ``image`` objects for poster URLs.

Series detail: ``/cms/routes/show/{alternate_id}`` -- returns all
season/episode metadata in a single nested response.

Episode lists: ``/cms/collections/{collection_id}`` with season filter
parameters -- returns per-season episode listings.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "discovery"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class _RawTitle:
    """Minimal title record from Discovery+ search results."""

    id: str  # alternateId for shows, numeric id for videos
    name: str
    type: str  # "tv" | "movie"
    year: str | None
    image_url: str | None


@dataclass
class _RawEpisode:
    """Minimal episode record from Discovery+ API."""

    id: str  # edit ID (used for playback)
    title: str
    season_number: int
    episode_number: int


# ---------------------------------------------------------------------------
# Client management
# ---------------------------------------------------------------------------

class DiscoveryClient:
    """Lightweight Discovery+ API client with anonymous auth support.

    Handles token acquisition and provides a consistent interface for
    API calls.  Supports both anonymous (bearer token from ``/token``)
    and authenticated (``st`` cookie) modes.

    Parameters
    ----------
    http:
        Shared HTTP client.
    st_cookie:
        Optional ``st`` cookie value for authenticated access.
    """

    def __init__(self, http: HttpClient, st_cookie: str | None = None) -> None:
        self._http = http
        self.device_id = str(uuid.uuid1())
        self.base_url = "https://eu1-prod-direct.discoveryplus.com"
        self.bearer_token: str | None = None
        self.access_token: str | None = None
        self.is_anonymous = True

        self.headers: dict[str, str] = {
            "accept": "*/*",
            "accept-language": "it,it-IT;q=0.9,en;q=0.8",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            ),
            "x-disco-client": "WEB:UNKNOWN:dsc:4.4.1",
        }

        self.cookies: dict[str, str] = {}

        if st_cookie:
            self._authenticate_with_cookie(st_cookie)
        else:
            self._authenticate_anonymous()

    def _authenticate_anonymous(self) -> None:
        """Obtain an anonymous bearer token."""
        params = {
            "deviceId": self.device_id,
            "realm": "dplay",
            "shortlived": "true",
        }
        headers = {
            "user-agent": self.headers["user-agent"],
            "x-device-info": (
                f"dsc/4.4.1 (desktop/desktop; Windows/NT 10.0; {self.device_id})"
            ),
            "x-disco-client": "WEB:UNKNOWN:dsc:4.4.1",
        }

        try:
            resp = self._http.get(
                "https://eu1-prod-direct.discoveryplus.com/token",
                headers=headers,
                params=params,
                use_curl=True,
            )
            resp.raise_for_status()
            self.bearer_token = resp.json()["data"]["attributes"]["token"]
            self.headers["Authorization"] = f"Bearer {self.bearer_token}"
            self.cookies = {"st": self.bearer_token}
            self.is_anonymous = True
            log.debug("Discovery+ anonymous token obtained")
        except Exception as exc:
            raise ServiceError(
                f"Failed to get Discovery+ anonymous token: {exc}",
                service_name=_SERVICE_TAG,
            ) from exc

    def _authenticate_with_cookie(self, st_cookie: str) -> None:
        """Authenticate using an ``st`` cookie."""
        android_headers = {
            "accept": "*/*",
            "user-agent": "androidtv dplus/20.8.1.2 (android/9; en-US; Build/1)",
            "x-disco-client": "ANDROIDTV:9:dplus:20.8.1.2",
            "x-disco-params": "realm=bolt,bid=dplus,features=ar",
            "x-device-info": (
                f"dplus/20.8.1.2 (NVIDIA/SHIELD; android/9; "
                f"{self.device_id}/{self.device_id})"
            ),
        }
        cookies = {"st": st_cookie}

        try:
            # Get access token.
            base = "https://default.any-any.prd.api.discoveryplus.com"
            resp = self._http.get(
                f"{base}/token",
                headers=android_headers,
                params={"realm": "bolt", "deviceId": self.device_id},
                use_curl=True,
            )
            resp.raise_for_status()
            self.access_token = resp.json()["data"]["attributes"]["token"]

            # Get routing config.
            resp = self._http.post(
                f"{base}/session-context/headwaiter/v1/bootstrap",
                headers=android_headers,
                use_curl=True,
            )
            resp.raise_for_status()
            config = resp.json()
            tenant = config["routing"]["tenant"]
            market = config["routing"]["homeMarket"]
            self.base_url = f"https://default.{tenant}-{market}.prd.api.discoveryplus.com"

            self.headers = android_headers
            self.cookies = cookies
            self.is_anonymous = False
            log.debug("Discovery+ authenticated for %s-%s", tenant, market)

        except Exception:
            log.warning(
                "Discovery+ authenticated mode failed, falling back to anonymous",
                exc_info=True,
            )
            self._authenticate_anonymous()


# Module-level client singleton.
_client: DiscoveryClient | None = None


def get_client(http: HttpClient, st_cookie: str | None = None) -> DiscoveryClient:
    """Get or create the Discovery+ client singleton."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = DiscoveryClient(http, st_cookie)
    return _client


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_titles(
    http: HttpClient,
    client: DiscoveryClient,
    query: str,
) -> list[_RawTitle]:
    """Search Discovery+ for titles matching *query*.

    Parameters
    ----------
    http:
        Shared HTTP client.
    client:
        Authenticated Discovery+ client.
    query:
        Free-text search string.

    Returns
    -------
    list[_RawTitle]
        Shows and videos matching the query.
    """
    url = f"{client.base_url}/cms/routes/search/result"
    params = {
        "include": "default",
        "decorators": "viewingHistory,isFavorite,playbackAllowed,contentAction,badges",
        "contentFilter[query]": query,
        "page[items.number]": "1",
        "page[items.size]": "20",
    }

    log.debug("Searching Discovery+: %s", query)

    try:
        resp = http.get(
            url, headers=client.headers, params=params, use_curl=True,
        )
        resp.raise_for_status()
    except Exception:
        log.error("Discovery+ search request failed", exc_info=True)
        return []

    data = resp.json()

    # Build image mapping.
    image_map: dict[str, str] = {}
    for element in data.get("included", []):
        if element.get("type") == "image":
            attrs = element.get("attributes", {})
            if attrs.get("kind") in ("poster", "poster_with_logo", "default"):
                image_map[element.get("id", "")] = attrs.get("src", "")

    results: list[_RawTitle] = []

    for element in data.get("included", []):
        element_type = element.get("type")
        if element_type not in ("show", "video"):
            continue

        attrs = element.get("attributes", {})

        # Find image URL.
        image_url: str | None = None
        relationships = element.get("relationships", {})
        images_data = relationships.get("images", {}).get("data", [])
        for img in images_data:
            img_id = img.get("id", "")
            if img_id in image_map:
                image_url = image_map[img_id]
                break

        # Extract year.
        year: str | None = None
        date_field = attrs.get("premiereDate") or attrs.get("airDate") or ""
        if date_field and "-" in date_field:
            year = date_field.split("-")[0]
        elif date_field and len(date_field) >= 4:
            year = date_field[:4]

        if element_type == "show":
            results.append(
                _RawTitle(
                    id=attrs.get("alternateId", ""),
                    name=attrs.get("name", ""),
                    type="tv",
                    year=year,
                    image_url=image_url,
                )
            )
        else:  # video
            results.append(
                _RawTitle(
                    id=element.get("id", ""),
                    name=attrs.get("name", ""),
                    type="movie",
                    year=year,
                    image_url=image_url,
                )
            )

    log.info("Discovery+ search for %r returned %d result(s)", query, len(results))
    return results


def get_show_episodes(
    http: HttpClient,
    client: DiscoveryClient,
    show_id: str,
) -> tuple[str, list[_RawEpisode]]:
    """Fetch all episodes for a Discovery+ show.

    Parameters
    ----------
    http:
        Shared HTTP client.
    client:
        Authenticated Discovery+ client.
    show_id:
        The ``alternateId`` of the show.

    Returns
    -------
    tuple[str, list[_RawEpisode]]
        ``(show_name, episodes_list)`` where episodes are sorted by
        ``(season, episode)`` and de-duplicated.
    """
    url = f"{client.base_url}/cms/routes/show/{show_id}"
    params = {
        "include": "default",
        "decorators": "viewingHistory,badges,isFavorite,contentAction",
    }

    log.debug("Fetching Discovery+ show info: %s", show_id)

    try:
        resp = http.get(
            url, headers=client.headers, params=params, use_curl=True,
        )
        resp.raise_for_status()
    except Exception:
        log.error("Failed to fetch Discovery+ show info", exc_info=True)
        return "Unknown", []

    data = resp.json()

    # Find show name.
    show_name = "Unknown"
    for item in data.get("included", []):
        if (
            item.get("attributes", {}).get("alternateId") == show_id
        ):
            show_name = item.get("attributes", {}).get("name", "Unknown")
            break

    # Collect episodes from the included data.
    all_episodes: list[_RawEpisode] = []
    seen_ids: set[str] = set()

    # Pass 1: Direct episodes in the response.
    for item in data.get("included", []):
        if item.get("type") != "video":
            continue
        attrs = item.get("attributes", {})
        season_num = attrs.get("seasonNumber")
        ep_num = attrs.get("episodeNumber")
        if season_num is None or ep_num is None:
            continue

        relationships = item.get("relationships", {})
        edit_id = (
            relationships.get("edit", {}).get("data", {}).get("id")
            or item.get("id", "")
        )

        if edit_id in seen_ids:
            continue
        seen_ids.add(edit_id)

        all_episodes.append(
            _RawEpisode(
                id=edit_id,
                title=attrs.get("name", f"Episode {ep_num}"),
                season_number=season_num,
                episode_number=ep_num,
            )
        )

    # Pass 2: Collection-based episode fetching.
    episodes_aliases = [
        "show-page-rail-episodes-tabbed-content",
        "generic-show-episodes",
    ]
    content = None
    for item in data.get("included", []):
        alias = item.get("attributes", {}).get("alias", "")
        if any(a in alias for a in episodes_aliases):
            content = item
            break

    # Fallback: look for any component with a seasonNumber filter.
    if not content:
        for item in data.get("included", []):
            attrs = item.get("attributes", {})
            comp = attrs.get("component") if isinstance(attrs, dict) else None
            if comp and isinstance(comp.get("filters"), list):
                if any(
                    f.get("id") == "seasonNumber"
                    for f in comp.get("filters", [])
                ):
                    content = item
                    break

    if content:
        content_id = content.get("id", "")
        show_params = (
            content.get("attributes", {})
            .get("component", {})
            .get("mandatoryParams", "")
        )

        # Find season filter options.
        season_filter = None
        filters = (
            content.get("attributes", {})
            .get("component", {})
            .get("filters", [])
        )
        for f in filters:
            if f.get("id") == "seasonNumber":
                season_filter = f
                break

        season_params = []
        if season_filter:
            season_params = [
                opt.get("parameter", "")
                for opt in season_filter.get("options", [])
            ]

        # Fetch episodes per season.
        for season_param in season_params:
            coll_url = (
                f"{client.base_url}/cms/collections/{content_id}"
                f"?{season_param}&{show_params}"
            )
            coll_params = {
                "include": "default",
                "decorators": "viewingHistory,badges,isFavorite,contentAction",
            }

            try:
                coll_resp = http.get(
                    coll_url, headers=client.headers,
                    params=coll_params, use_curl=True,
                )
                coll_resp.raise_for_status()
                season_data = coll_resp.json()

                for item in season_data.get("included", []):
                    if item.get("type") != "video":
                        continue
                    attrs = item.get("attributes", {})
                    if attrs.get("videoType") != "EPISODE":
                        continue

                    relationships = item.get("relationships", {})
                    edit_id = (
                        relationships.get("edit", {}).get("data", {}).get("id")
                        or item.get("id", "")
                    )

                    if edit_id in seen_ids:
                        continue
                    seen_ids.add(edit_id)

                    all_episodes.append(
                        _RawEpisode(
                            id=edit_id,
                            title=attrs.get("name", ""),
                            season_number=attrs.get("seasonNumber", 0),
                            episode_number=attrs.get("episodeNumber", 0),
                        )
                    )

            except Exception:
                log.debug(
                    "Failed to fetch Discovery+ collection for season",
                    exc_info=True,
                )

    # Sort by (season, episode).
    all_episodes.sort(key=lambda e: (e.season_number, e.episode_number))

    log.info(
        "Discovery+ show %r has %d episode(s)",
        show_name, len(all_episodes),
    )
    return show_name, all_episodes
