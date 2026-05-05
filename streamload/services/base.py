"""Abstract base class for streaming service plugins.

Every service module subclasses :class:`ServiceBase` and decorates itself
with ``@ServiceRegistry.register`` so the registry can discover it at
import time.  The base class enforces a uniform interface for searching,
browsing seasons/episodes, and resolving stream bundles -- keeping the
download engine completely decoupled from service-specific logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from streamload.models.media import (
    AuthSession,
    Episode,
    MediaEntry,
    MediaType,
    Season,
    ServiceCategory,
)
from streamload.models.stream import StreamBundle
from streamload.utils.http import HttpClient


class ServiceBase(ABC):
    """Abstract base class for streaming service plugins.

    Every service must declare these class attributes:

    - **name** -- Display name, e.g. ``"StreamingCommunity"``
    - **short_name** -- Short identifier, e.g. ``"sc"``
    - **domains** -- Known domains the service operates on
    - **category** -- :class:`ServiceCategory` declaring supported content
    - **language** -- Primary language code: ``"it"``, ``"en"``, ``"multi"``
    - **requires_login** -- Whether credentials are needed before use

    Subclasses must implement the four abstract methods: :meth:`search`,
    :meth:`get_seasons`, :meth:`get_episodes`, and :meth:`get_streams`.
    """

    name: str
    short_name: str
    domains: list[str]
    category: ServiceCategory
    language: str
    requires_login: bool = False

    def __init__(self, http_client: HttpClient) -> None:
        self._http: HttpClient = http_client
        self._session: AuthSession | None = None
        self._resolver = None
        self._resolved_domain: str | None = None

    # -- Authentication -----------------------------------------------------

    @property
    def is_authenticated(self) -> bool:
        """Return ``True`` if an active session is held."""
        return self._session is not None

    def authenticate(self, credentials: dict[str, str]) -> AuthSession | None:
        """Authenticate with the service.

        The default implementation is a no-op that returns ``None``.
        Override in services where :attr:`requires_login` is ``True``.

        Parameters
        ----------
        credentials:
            A mapping of credential keys (e.g. ``"username"``,
            ``"password"``) specific to this service.

        Returns
        -------
        AuthSession | None
            A populated session on success, ``None`` on failure or when
            authentication is not supported.
        """
        return None

    def set_session(self, session: AuthSession) -> None:
        """Inject an externally-obtained authentication session.

        Useful when restoring session data that was cached across runs
        (cookies, tokens) without re-prompting for credentials.
        """
        self._session = session

    # -- Abstract interface -------------------------------------------------

    @abstractmethod
    def search(self, query: str) -> list[MediaEntry]:
        """Search for content on this service.

        Parameters
        ----------
        query:
            Free-text search string entered by the user.

        Returns
        -------
        list[MediaEntry]
            Zero or more results.  Each entry carries enough metadata for
            display and for subsequent calls to :meth:`get_seasons` or
            :meth:`get_streams`.
        """
        ...

    @abstractmethod
    def get_seasons(self, entry: MediaEntry) -> list[Season]:
        """Get seasons for a series or anime.

        Film-only services should return an empty list.  The returned
        seasons are ordered by ``Season.number``.

        Parameters
        ----------
        entry:
            A :class:`MediaEntry` previously returned by :meth:`search`.
        """
        ...

    @abstractmethod
    def get_episodes(self, season: Season) -> list[Episode]:
        """Get episodes for a given season.

        Film-only services should return an empty list.

        Parameters
        ----------
        season:
            A :class:`Season` previously returned by :meth:`get_seasons`.
        """
        ...

    @abstractmethod
    def get_streams(self, item: Episode | MediaEntry) -> StreamBundle:
        """Resolve available streams for a downloadable item.

        The returned :class:`StreamBundle` contains all video, audio, and
        subtitle tracks the service offers for *item*, along with DRM
        metadata when applicable.

        Parameters
        ----------
        item:
            Either an :class:`Episode` (for series/anime content) or a
            :class:`MediaEntry` (for films).
        """
        ...

    # -- Convenience helpers ------------------------------------------------

    def attach_resolver(self, resolver: Any) -> None:
        """Wire a DomainResolver. Subsequent base_url reads route through it."""
        self._resolver = resolver
        self._resolved_domain: str | None = None

    @property
    def base_url(self) -> str:
        """Return ``https://<resolved>`` via DomainResolver when attached.

        Falls back to ``https://{domains[0]}`` when no resolver is attached
        (used by tests / standalone scripts).
        """
        resolver = getattr(self, "_resolver", None)
        if resolver is not None:
            if getattr(self, "_resolved_domain", None) is None:
                self._resolved_domain = resolver.resolve(self.short_name).domain
            return f"https://{self._resolved_domain}"
        return f"https://{self.domains[0]}" if self.domains else ""

    def supports_type(self, media_type: MediaType) -> bool:
        """Check whether this service can provide the given content type.

        The mapping is driven by :attr:`category`:

        - ``FILM_SERIE`` -- supports both ``FILM`` and ``SERIE``
        - ``FILM`` -- supports ``FILM`` only
        - ``SERIE`` -- supports ``SERIE`` only
        - ``ANIME`` -- supports ``ANIME`` only
        """
        if self.category == ServiceCategory.FILM_SERIE:
            return media_type in (MediaType.FILM, MediaType.SERIE)
        if self.category == ServiceCategory.FILM:
            return media_type == MediaType.FILM
        if self.category == ServiceCategory.SERIE:
            return media_type == MediaType.SERIE
        if self.category == ServiceCategory.ANIME:
            return media_type == MediaType.ANIME
        return False

    # -- Dunder helpers -----------------------------------------------------

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} '{self.name}' ({self.short_name})>"
