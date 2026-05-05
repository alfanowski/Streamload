"""Factory that wires the standard source chain for production use."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .cache import DomainCache
from .circuit_breaker import CircuitBreaker
from .resolver import DomainResolver
from .sources import (
    CacheSource,
    ConfigSource,
    DiscoverySource,
    ProbeSource,
    RemoteSource,
)
from .trusted_keys import TRUSTED_KEYS
from .validator import validate_domain

DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6h
MANIFEST_FILENAME = "domains.json"


def build_resolver(
    *,
    http: Any,
    config_overrides: dict[str, str],
    probe_seeds: dict[str, list[str]],
    cache_path: Path,
    repo: str,
    branch: str = "main",
    discovery_seeds: dict[str, dict[str, list[str]]] | None = None,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    breaker_threshold: int = 3,
    lang: str = "it",
) -> DomainResolver:
    """Build the production resolver with the full 5-source chain.

    Source priority (highest to lowest):

        1. ConfigSource     -- user override in config.json
        2. CacheSource      -- last validated domain (within TTL)
        3. RemoteSource     -- signed manifest from GitHub raw / jsDelivr
        4. ProbeSource      -- hardcoded ``ServiceBase.domains`` list
        5. DiscoverySource  -- prefix x TLD permutation (last resort)

    Each candidate runs through the active validator before being accepted.
    The first validated domain wins; the result is cached.
    """
    cache = DomainCache(cache_path)
    sources = [
        ConfigSource(overrides=config_overrides),
        CacheSource(cache=cache, ttl_seconds=cache_ttl_seconds),
        RemoteSource(
            http=http,
            repo=repo,
            branch=branch,
            manifest_filename=MANIFEST_FILENAME,
            trusted_keys=TRUSTED_KEYS,
        ),
        ProbeSource(seeds=probe_seeds),
        DiscoverySource(seeds=discovery_seeds or {}),
    ]
    return DomainResolver(
        sources=sources,
        cache=cache,
        validator=validate_domain,
        http=http,
        breaker=CircuitBreaker(threshold=breaker_threshold),
        lang=lang,
    )
