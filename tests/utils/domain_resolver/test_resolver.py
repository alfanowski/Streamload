from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from streamload.utils.domain_resolver.cache import DomainCache
from streamload.utils.domain_resolver.circuit_breaker import CircuitBreaker
from streamload.utils.domain_resolver.errors import DomainResolutionError
from streamload.utils.domain_resolver.resolver import DomainResolver
from streamload.utils.domain_resolver.sources.base import DomainSource


class _StaticSource(DomainSource):
    def __init__(self, name: str, mapping: dict[str, list[str]]):
        self.name = name
        self._m = mapping
    def candidates(self, short_name: str) -> list[str]:
        return list(self._m.get(short_name, []))


@pytest.fixture
def cache(tmp_path: Path) -> DomainCache:
    return DomainCache(tmp_path / "c.json")


def _validator(allowed: set[str]):
    def fn(http, domain, lang="it"):
        return domain in allowed
    return fn


def test_returns_first_validated_candidate(cache: DomainCache):
    sources = [
        _StaticSource("config", {"sc": ["bad1.tld"]}),
        _StaticSource("remote", {"sc": ["bad2.tld", "good.tld", "also-good.tld"]}),
    ]
    r = DomainResolver(
        sources=sources,
        cache=cache,
        validator=_validator({"good.tld", "also-good.tld"}),
        http=MagicMock(),
        breaker=CircuitBreaker(threshold=3),
    )
    resolved = r.resolve("sc")
    assert resolved.domain == "good.tld"
    assert resolved.source == "remote"


def test_writes_to_cache_on_success(cache: DomainCache):
    sources = [_StaticSource("remote", {"sc": ["x.tld"]})]
    r = DomainResolver(
        sources=sources,
        cache=cache,
        validator=_validator({"x.tld"}),
        http=MagicMock(),
        breaker=CircuitBreaker(threshold=3),
    )
    r.resolve("sc")
    entry = cache.get("sc")
    assert entry is not None
    assert entry["domain"] == "x.tld"


def test_skips_remaining_sources_after_first_validated_hit(cache: DomainCache):
    s1 = _StaticSource("config", {"sc": ["x.tld"]})
    s2 = MagicMock()
    s2.name = "remote"
    s2.candidates.return_value = []
    r = DomainResolver(
        sources=[s1, s2],
        cache=cache,
        validator=_validator({"x.tld"}),
        http=MagicMock(),
        breaker=CircuitBreaker(threshold=3),
    )
    r.resolve("sc")
    s2.candidates.assert_not_called()


def test_raises_when_no_source_yields_validated_domain(cache: DomainCache):
    sources = [_StaticSource("probe", {"sc": ["nope.tld"]})]
    r = DomainResolver(
        sources=sources,
        cache=cache,
        validator=_validator(set()),
        http=MagicMock(),
        breaker=CircuitBreaker(threshold=3),
    )
    with pytest.raises(DomainResolutionError):
        r.resolve("sc")


def test_invalidate_clears_cache_and_resets_breaker(cache: DomainCache):
    cache.set("sc", domain="x.tld", source="cache", validated_at=1.0)
    breaker = CircuitBreaker(threshold=2)
    breaker.record_failure("sc")
    r = DomainResolver(
        sources=[],
        cache=cache,
        validator=_validator(set()),
        http=MagicMock(),
        breaker=breaker,
    )
    r.invalidate("sc")
    assert cache.get("sc") is None


def test_record_failure_invalidates_when_breaker_opens(cache: DomainCache):
    cache.set("sc", domain="x.tld", source="cache", validated_at=1.0)
    breaker = CircuitBreaker(threshold=2)
    r = DomainResolver(
        sources=[],
        cache=cache,
        validator=_validator(set()),
        http=MagicMock(),
        breaker=breaker,
    )
    r.record_failure("sc")
    assert cache.get("sc") is not None  # not yet
    r.record_failure("sc")
    assert cache.get("sc") is None  # breaker opened -> invalidated
