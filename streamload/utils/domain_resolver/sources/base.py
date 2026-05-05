"""Source ABC for the resolver chain.

Each source produces an ordered list of *candidate* domains for a service.
Candidates are then validated by the resolver before being accepted.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class DomainSource(ABC):
    """Produces ordered candidate domains for a service."""

    name: str

    @abstractmethod
    def candidates(self, short_name: str) -> list[str]:
        """Return the candidate domains, most-preferred first. Empty if none."""
        ...
