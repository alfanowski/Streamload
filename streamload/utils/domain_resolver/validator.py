"""Active health check that confirms a candidate domain serves the live site.

The check is service-shaped: it fetches ``/<lang>`` and verifies that the
response is an Inertia.js page with both ``version`` and ``props`` in the
``data-page`` JSON. This is enough to reject parking pages, ISP captive
portals, and squatted-but-online domains.

Currently only the StreamingCommunity shape is checked. When more services
are added, accept a ``shape`` parameter and dispatch.
"""
from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from streamload.utils.logger import get_logger

log = get_logger(__name__)

_VALIDATION_TIMEOUT_HINT = 10  # seconds; HttpClient honors its own config


def validate_domain(http: Any, domain: str, *, lang: str = "it") -> bool:
    """Return True if ``https://{domain}/{lang}`` serves a valid Inertia page."""
    url = f"https://{domain}/{lang}"
    try:
        resp = http.get(url, use_curl=True)
    except Exception:
        log.debug("validate_domain: GET failed for %s", url, exc_info=True)
        return False

    if getattr(resp, "status_code", 0) != 200:
        log.debug("validate_domain: status=%s for %s", resp.status_code, url)
        return False

    text = getattr(resp, "text", "") or ""
    soup = BeautifulSoup(text, "html.parser")
    app = soup.find("div", {"id": "app"})
    if app is None:
        return False

    data_page = app.get("data-page")
    if not data_page:
        return False

    try:
        page = json.loads(data_page)
    except (json.JSONDecodeError, TypeError):
        return False

    if not isinstance(page, dict):
        return False
    if "version" not in page or "props" not in page:
        return False

    return True
