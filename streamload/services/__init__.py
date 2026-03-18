"""Service plugin registry and parallel search orchestration.

Services register themselves at import time via the
:meth:`ServiceRegistry.register` class-method decorator.  Call
:func:`load_services` once at startup to trigger all imports, then use
the registry to enumerate, filter, instantiate, and search across every
available streaming service.

Example::

    from streamload.services import ServiceRegistry, load_services
    from streamload.utils.http import HttpClient

    load_services()
    with HttpClient() as http:
        instances = ServiceRegistry.instantiate_all(http, config)
        results = ServiceRegistry.search_all("breaking bad", instances)
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Callable

from streamload.models.config import AppConfig
from streamload.models.media import SearchResult, ServiceCategory
from streamload.services.base import ServiceBase
from streamload.utils.http import HttpClient

logger = logging.getLogger("streamload.services")

# Type alias for the optional progress callback accepted by search_all.
# Signature: callback(service_name, status, result_count)
ProgressCallback = Callable[[str, str, int], None]


class ServiceRegistry:
    """Registry for streaming service plugins.

    Services register via the :meth:`register` class-method decorator::

        @ServiceRegistry.register
        class MyService(ServiceBase):
            ...

    The registry is a class-level singleton -- all state lives on the
    class itself so that registration works at import time without
    requiring an explicit instance.
    """

    _services: dict[str, type[ServiceBase]] = {}

    # -- Registration -------------------------------------------------------

    @classmethod
    def register(cls, service_class: type[ServiceBase]) -> type[ServiceBase]:
        """Decorator to register a :class:`ServiceBase` subclass.

        Usage::

            @ServiceRegistry.register
            class StreamingCommunity(ServiceBase):
                short_name = "sc"
                ...

        Returns the class unmodified so it can still be used directly.
        """
        key = service_class.short_name
        if key in cls._services:
            logger.warning(
                "Overwriting existing service registration for %r (%s -> %s)",
                key,
                cls._services[key].__name__,
                service_class.__name__,
            )
        cls._services[key] = service_class
        logger.debug(
            "Registered service: %s (%s)", service_class.name, key,
        )
        return service_class

    # -- Lookup -------------------------------------------------------------

    @classmethod
    def get_all(cls) -> list[type[ServiceBase]]:
        """Return all registered service classes, sorted by display name."""
        return sorted(cls._services.values(), key=lambda s: s.name)

    @classmethod
    def get_by_category(cls, category: ServiceCategory) -> list[type[ServiceBase]]:
        """Return service classes that match *category*.

        ``FILM_SERIE`` services appear when filtering by either ``FILM``
        or ``SERIE``, since they handle both content types.
        """
        matches: list[type[ServiceBase]] = []
        for svc in cls._services.values():
            if svc.category == category:
                matches.append(svc)
            elif (
                svc.category == ServiceCategory.FILM_SERIE
                and category in (ServiceCategory.FILM, ServiceCategory.SERIE)
            ):
                matches.append(svc)
        return sorted(matches, key=lambda s: s.name)

    @classmethod
    def get_by_short_name(cls, short_name: str) -> type[ServiceBase] | None:
        """Return the service class registered under *short_name*, or ``None``."""
        return cls._services.get(short_name)

    @classmethod
    def count(cls) -> int:
        """Return the number of registered services."""
        return len(cls._services)

    # -- Instantiation ------------------------------------------------------

    @classmethod
    def instantiate_all(
        cls,
        http_client: HttpClient,
        config: AppConfig,
    ) -> dict[str, ServiceBase]:
        """Create live instances of every registered service.

        Parameters
        ----------
        http_client:
            Shared HTTP client injected into each service.
        config:
            Application configuration (available for future per-service
            tuning; currently unused beyond construction).

        Returns
        -------
        dict[str, ServiceBase]
            Mapping of ``short_name`` to service instance.  Services that
            fail to instantiate are logged and silently skipped.
        """
        instances: dict[str, ServiceBase] = {}
        for short_name, service_cls in cls._services.items():
            try:
                instances[short_name] = service_cls(http_client)
            except Exception:
                logger.error(
                    "Failed to instantiate %s (%s)",
                    service_cls.name,
                    short_name,
                    exc_info=True,
                )
        return instances

    # -- Parallel search ----------------------------------------------------

    @classmethod
    def search_all(
        cls,
        query: str,
        instances: dict[str, ServiceBase],
        *,
        max_workers: int = 5,
        on_progress: ProgressCallback | None = None,
    ) -> list[SearchResult]:
        """Search across all service instances in parallel.

        Each service is queried in its own thread via
        :class:`~concurrent.futures.ThreadPoolExecutor`.  A failure in
        one service never prevents results from other services.

        Parameters
        ----------
        query:
            Free-text search string entered by the user.
        instances:
            Mapping of ``short_name`` to live :class:`ServiceBase` instances
            (as returned by :meth:`instantiate_all`).
        max_workers:
            Maximum thread-pool size.  Defaults to 5 which is a good
            balance between throughput and polite request rates.
        on_progress:
            Optional callback invoked as each service completes (or
            fails).  Signature::

                on_progress(service_name: str, status: str, count: int)

            *status* is ``"ok"`` on success or ``"error"`` on failure.
            *count* is the number of results returned (0 on error).

        Returns
        -------
        list[SearchResult]
            Aggregated results from all services, sorted by
            ``match_score`` descending (best matches first).
        """
        if not instances:
            return []

        all_results: list[SearchResult] = []

        def _search_one(service: ServiceBase) -> list[SearchResult]:
            """Run a single service's search and wrap entries as SearchResult."""
            entries = service.search(query)
            return [
                SearchResult(
                    entry=entry,
                    service_display_name=service.name,
                    match_score=entry.match_score if hasattr(entry, "match_score") else 0.0,
                )
                for entry in entries
            ]

        # Cap workers to the number of services to avoid idle threads.
        effective_workers = min(max_workers, len(instances))

        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            future_to_name: dict[Future[list[SearchResult]], str] = {}
            for short_name, service in instances.items():
                future = pool.submit(_search_one, service)
                future_to_name[future] = short_name

            for future in as_completed(future_to_name):
                short_name = future_to_name[future]
                service = instances[short_name]
                try:
                    results = future.result()
                    all_results.extend(results)
                    logger.debug(
                        "Search complete for %s: %d result(s)",
                        service.name,
                        len(results),
                    )
                    if on_progress is not None:
                        on_progress(service.name, "ok", len(results))
                except Exception:
                    logger.error(
                        "Search failed for %s (%s)",
                        service.name,
                        short_name,
                        exc_info=True,
                    )
                    if on_progress is not None:
                        on_progress(service.name, "error", 0)

        # Best matches first.
        all_results.sort(key=lambda r: r.match_score, reverse=True)
        return all_results


# ---------------------------------------------------------------------------
# Service auto-discovery
# ---------------------------------------------------------------------------

def load_services() -> None:
    """Import all service modules to trigger ``@ServiceRegistry.register``.

    Call this function once during application startup, *before* using any
    registry lookup methods.  Import errors for individual services are
    logged and silently swallowed so that a broken service never prevents
    the rest of the application from starting.
    """
    _service_modules = (
        "animeunity",
        "animeworld",
        "crunchyroll",
        "discovery",
        "dmax",
        "foodnetwork",
        "guardaserie",
        "homegardentv",
        "mediasetinfinity",
        "mostraguarda",
        "nove",
        "raiplay",
        "realtime",
        "streamingcommunity",
        "tubitv",
    )
    for module_name in _service_modules:
        fqn = f"streamload.services.{module_name}"
        try:
            __import__(fqn)
        except Exception:
            logger.error("Failed to load service module %s", fqn, exc_info=True)
