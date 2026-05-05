"""Last-resort source: hardcoded historical domains from the service class."""
from __future__ import annotations

from .base import DomainSource


class ProbeSource(DomainSource):
    """Returns the service's hardcoded fallback list (last-known-good seed)."""

    name = "probe"

    def __init__(self, *, seeds: dict[str, list[str]]) -> None:
        self._seeds = seeds

    def candidates(self, short_name: str) -> list[str]:
        return list(self._seeds.get(short_name, []))
