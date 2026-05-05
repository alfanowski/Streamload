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
from collections.abc import Callable, Iterator, Sequence
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
                if self._validate(self._http, domain, lang=self._lang):
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

    # -- Quality-aware mirror selection -----------------------------------
    #
    # Some services serve different content quality on different mirrors
    # (e.g. one mirror has 1080p variants, another only up to 720p). The
    # caller can probe alternatives via iter_alternatives() and remember a
    # quality-preferred mirror via set_preferred(...).

    _PREFERRED_TTL_SECONDS = 24 * 60 * 60  # 24h -- quality is stable

    def iter_alternatives(
        self,
        short_name: str,
        *,
        max_attempts: int | None = 8,
        skip_sources: tuple[str, ...] = ("discovery",),
    ) -> Iterator[str]:
        """Yield validated candidate domains *other than* the cached primary.

        Walks the source chain lazily: each candidate is validated on
        demand and yielded if valid. Useful for opportunistic upgrades
        (e.g. find a mirror that serves higher-quality streams).

        Parameters
        ----------
        short_name:
            The service identifier.
        max_attempts:
            Maximum number of candidates to *attempt* validating across
            all sources. Each attempt costs an HTTP probe (~2 s in fast
            mode). Defaults to 8 to keep total worst-case cost ~16 s.
            Pass ``None`` to disable the cap (not recommended in
            interactive contexts).
        skip_sources:
            Source names to skip entirely. By default the
            ``DiscoverySource`` is skipped because its TLD-permutation
            candidate space (~50+ entries) makes exhaustive validation
            impractical for interactive use. The probe-from-discovery
            path is reserved for the resolver's primary-recovery flow.

        The currently cached domain (if any) is skipped. Duplicates
        across sources are de-duped.
        """
        current_entry = self._cache.get(short_name)
        current_domain = (
            current_entry.get("domain") if isinstance(current_entry, dict) else None
        )
        seen: set[str] = set()
        if current_domain:
            seen.add(current_domain)

        attempts = 0
        for source in self._sources:
            if source.name in skip_sources:
                continue
            try:
                candidates = source.candidates(short_name)
            except Exception:
                log.warning(
                    "Source %s raised during iter_alternatives; skipping",
                    source.name, exc_info=True,
                )
                continue
            for domain in candidates:
                if not domain or domain in seen:
                    continue
                seen.add(domain)
                if max_attempts is not None and attempts >= max_attempts:
                    return
                attempts += 1
                if self._validate(self._http, domain, lang=self._lang):
                    yield domain

    def get_preferred(self, short_name: str, *, tag: str) -> str | None:
        """Return the cached *tag*-preferred domain for *short_name*.

        Tags are caller-defined (e.g. ``"fhd"``). The entry expires after
        :attr:`_PREFERRED_TTL_SECONDS`. Use ``set_preferred`` to write.
        """
        key = f"{short_name}:{tag}"
        if not self._cache.is_fresh(key, ttl_seconds=self._PREFERRED_TTL_SECONDS):
            return None
        entry = self._cache.get(key)
        if not isinstance(entry, dict):
            return None
        return entry.get("domain")

    def set_preferred(self, short_name: str, *, tag: str, domain: str) -> None:
        """Cache *domain* as the *tag*-preferred mirror for *short_name*."""
        key = f"{short_name}:{tag}"
        self._cache.set(
            key,
            domain=domain,
            source=f"preferred-{tag}",
            validated_at=time.time(),
        )
        log.info("Cached %s-preferred mirror for %s: %s", tag, short_name, domain)
