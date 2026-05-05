"""DomainResolver — orchestrates the source chain, validator and cache.

Public flow:

    resolve(short_name) -> ResolvedDomain
        for each source in priority order:
            for each candidate from that source:
                if validator(candidate) is True:
                    cache.set(...)
                    breaker.reset(short_name)
                    return ResolvedDomain(...)
        raise DomainResolutionError

Failures observed at runtime by callers (downstream HTTP errors) feed back
in via record_failure(); when the breaker opens, the cache is invalidated
so the next resolve() walks the chain afresh.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from streamload.utils.logger import get_logger

from .cache import DomainCache
from .circuit_breaker import CircuitBreaker
from .errors import DomainResolutionError
from .models import ResolvedDomain
from .sources.base import DomainSource

log = get_logger(__name__)

Validator = Callable[[Any, str], bool]  # (http, domain) -> ok
ValidatorWithLang = Callable[[Any, str, str], bool]


class DomainResolver:
    def __init__(
        self,
        *,
        sources: Sequence[DomainSource],
        cache: DomainCache,
        validator: Callable[..., bool],
        http: Any,
        breaker: CircuitBreaker,
        lang: str = "it",
    ) -> None:
        self._sources = list(sources)
        self._cache = cache
        self._validate = validator
        self._http = http
        self._breaker = breaker
        self._lang = lang

    def resolve(self, short_name: str) -> ResolvedDomain:
        for source in self._sources:
            try:
                candidates = source.candidates(short_name)
            except Exception:
                log.warning("Source %s raised; skipping", source.name, exc_info=True)
                continue

            for domain in candidates:
                if self._validate(self._http, domain, self._lang):
                    now = time.time()
                    self._cache.set(
                        short_name,
                        domain=domain,
                        source=source.name,
                        validated_at=now,
                    )
                    self._breaker.reset(short_name)
                    log.info(
                        "Resolved %s -> %s via %s",
                        short_name, domain, source.name,
                    )
                    return ResolvedDomain(
                        domain=domain,
                        source=source.name,
                        validated_at=now,
                    )
                log.debug("Candidate %s from %s did not validate", domain, source.name)

        raise DomainResolutionError(
            f"no source produced a validated domain for service {short_name!r}"
        )

    def record_failure(self, short_name: str) -> None:
        self._breaker.record_failure(short_name)
        if self._breaker.is_open(short_name):
            log.warning(
                "Circuit breaker opened for %s; invalidating cache", short_name,
            )
            self.invalidate(short_name)

    def record_success(self, short_name: str) -> None:
        self._breaker.record_success(short_name)

    def invalidate(self, short_name: str) -> None:
        self._cache.invalidate(short_name)
        self._breaker.reset(short_name)
