from pathlib import Path

import pytest

from streamload.utils.domain_resolver.cache import DomainCache
from streamload.utils.domain_resolver.sources.cache_source import CacheSource


@pytest.fixture
def cache(tmp_path: Path) -> DomainCache:
    return DomainCache(tmp_path / "c.json")


def test_returns_empty_when_cache_missing(cache: DomainCache):
    src = CacheSource(cache=cache, ttl_seconds=60)
    assert src.candidates("sc") == []


def test_returns_cached_domain_when_fresh(cache: DomainCache):
    import time
    cache.set("sc", domain="x.tld", source="remote-github", validated_at=time.time())
    src = CacheSource(cache=cache, ttl_seconds=60)
    assert src.candidates("sc") == ["x.tld"]


def test_returns_empty_when_cache_stale(cache: DomainCache):
    cache.set("sc", domain="x.tld", source="cache", validated_at=0.0)
    src = CacheSource(cache=cache, ttl_seconds=10)
    assert src.candidates("sc") == []


def test_name(cache: DomainCache):
    assert CacheSource(cache=cache, ttl_seconds=1).name == "cache"
