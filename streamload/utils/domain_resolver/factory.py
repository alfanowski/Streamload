"""Factory that wires the standard source chain for production use."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .cache import DomainCache
from .circuit_breaker import CircuitBreaker
from .resolver import DomainResolver
from .sources import CacheSource, ConfigSource, ProbeSource, RemoteSource
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
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    breaker_threshold: int = 3,
    lang: str = "it",
) -> DomainResolver:
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
    ]
    return DomainResolver(
        sources=sources,
        cache=cache,
        validator=validate_domain,
        http=http,
        breaker=CircuitBreaker(threshold=breaker_threshold),
        lang=lang,
    )
