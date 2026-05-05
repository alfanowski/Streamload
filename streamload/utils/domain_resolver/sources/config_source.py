"""Source that reads per-service overrides from the user config."""
from __future__ import annotations

from urllib.parse import urlparse

from .base import DomainSource


def _normalize(value: str) -> str:
    """Return bare hostname even if user wrote a full URL."""
    s = value.strip()
    if not s:
        return ""
    if "://" in s:
        parsed = urlparse(s)
        return parsed.netloc or ""
    return s.split("/", 1)[0]


class ConfigSource(DomainSource):
    """Reads overrides from ``AppConfig.services.<short_name>.base_url``."""

    name = "config"

    def __init__(self, *, overrides: dict[str, str]) -> None:
        self._overrides = overrides

    def candidates(self, short_name: str) -> list[str]:
        raw = self._overrides.get(short_name, "")
        host = _normalize(raw)
        return [host] if host else []
