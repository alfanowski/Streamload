"""Web scraping logic for MostraGuarda.

MostraGuarda is a film-only service that does not have its own search
API.  Instead, search is delegated to TMDB (The Movie Database) which
provides rich metadata.  The actual video content is resolved by looking
up the IMDB ID on the MostraGuarda server.

Film resolution: ``/set-movie-a/{imdb_id}`` -- returns an HTML page
containing a ``<ul class="_player-mirrors">`` with ``<li>`` elements
whose ``data-link`` attributes point to SuperVideo embeds.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "mostraguarda"

# The MostraGuarda streaming server domain (may differ from the search domain).
_STREAM_BASE = "https://mostraguarda.stream"


def resolve_player_url(
    http: HttpClient,
    imdb_id: str,
) -> str | None:
    """Resolve the SuperVideo player URL for a film via its IMDB ID.

    Parameters
    ----------
    http:
        Shared HTTP client.
    imdb_id:
        The IMDB ID of the film (e.g. ``"tt1234567"``).

    Returns
    -------
    str | None
        The SuperVideo embed URL, or ``None`` if the film is not found
        or no SuperVideo mirror is available.
    """
    url = f"{_STREAM_BASE}/set-movie-a/{imdb_id}"
    log.debug("Resolving MostraGuarda film: %s", url)

    try:
        resp = http.get(url)
        resp.raise_for_status()
    except Exception:
        log.error("MostraGuarda request failed for IMDB ID %s", imdb_id, exc_info=True)
        return None

    if "not found" in resp.text.lower():
        log.warning("Film not found on MostraGuarda: %s", imdb_id)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    mirrors_list = soup.find("ul", class_="_player-mirrors")
    if not mirrors_list:
        log.warning("No player mirrors found for IMDB ID %s", imdb_id)
        return None

    player_items = mirrors_list.find_all("li")
    if not player_items:
        log.warning("Empty player mirrors list for IMDB ID %s", imdb_id)
        return None

    # Prefer SuperVideo mirror.
    for li in player_items:
        data_link = li.get("data-link", "")
        if data_link and "supervideo" in data_link.lower():
            player_url = (
                "https:" + data_link if data_link.startswith("//") else data_link
            )
            log.debug("Found SuperVideo mirror: %s", player_url)
            return player_url

    # Fall back to the first available mirror.
    first_link = player_items[0].get("data-link", "")
    if first_link:
        player_url = (
            "https:" + first_link if first_link.startswith("//") else first_link
        )
        log.debug("Using first available mirror: %s", player_url)
        return player_url

    log.warning("No usable player link found for IMDB ID %s", imdb_id)
    return None
