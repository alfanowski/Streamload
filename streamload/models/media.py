"""Media data models for Streamload.

Defines core content types used across all services: media entries,
seasons, episodes, search results, and authentication sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MediaType(Enum):
    """Content type classification."""

    FILM = "film"
    SERIE = "serie"
    ANIME = "anime"


class ServiceCategory(Enum):
    """Service capability classification.

    Determines which content types a service can provide.
    FILM_SERIE indicates the service handles both films and series.
    """

    FILM = "film"
    SERIE = "serie"
    ANIME = "anime"
    FILM_SERIE = "film_serie"


@dataclass
class MediaEntry:
    """A single media item returned by a service.

    Represents a film, series, or anime title with enough metadata
    for display in search results and for fetching stream data.
    """

    id: str
    title: str
    type: MediaType
    url: str
    service: str  # service short_name, e.g. "sc"
    year: int | None = None
    genre: str | None = None
    image_url: str | None = None
    description: str | None = None


@dataclass
class Season:
    """A season within a series or anime."""

    number: int
    episode_count: int = 0
    title: str | None = None
    id: str | None = None


@dataclass
class Episode:
    """A single episode within a season."""

    number: int
    season_number: int
    title: str
    url: str
    id: str | None = None
    duration: int | None = None  # seconds


@dataclass
class SearchResult:
    """A media entry wrapped with service display info and relevance score.

    Used by the CLI to render search result tables across multiple services.
    """

    entry: MediaEntry
    service_display_name: str  # e.g. "StreamingCommunity"
    match_score: float = 0.0  # 0.0-1.0 fuzzy match


@dataclass
class AuthSession:
    """Cached authentication state for a service session.

    Held in memory only -- never persisted to disk. Expires when the
    application exits or when ``expires_at`` is reached.
    """

    cookies: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    expires_at: float | None = None  # Unix timestamp; None = session-only
