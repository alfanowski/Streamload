"""Tests for DomainResolver.iter_alternatives + get/set_preferred (quality-aware)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from streamload.utils.domain_resolver.cache import DomainCache
from streamload.utils.domain_resolver.circuit_breaker import CircuitBreaker
from streamload.utils.domain_resolver.resolver import DomainResolver
from streamload.utils.domain_resolver.sources.base import DomainSource


class _StaticSource(DomainSource):
    def __init__(self, name: str, mapping: dict[str, list[str]]):
        self.name = name
        self._m = mapping

    def candidates(self, short_name: str) -> list[str]:
        return list(self._m.get(short_name, []))


def _validator(allowed: set[str]):
    def fn(http, domain, lang="it"):
        return domain in allowed
    return fn


@pytest.fixture
def cache(tmp_path: Path) -> DomainCache:
    return DomainCache(tmp_path / "c.json")


# -- iter_alternatives --------------------------------------------------

def test_iter_alternatives_skips_currently_cached_primary(cache: DomainCache):
    cache.set("sc", domain="primary.tld", source="probe", validated_at=1.0)
    sources = [_StaticSource("p", {"sc": ["primary.tld", "alt1.tld", "alt2.tld"]})]
    r = DomainResolver(
        sources=sources, cache=cache,
        validator=_validator({"primary.tld", "alt1.tld", "alt2.tld"}),
        http=MagicMock(), breaker=CircuitBreaker(threshold=3),
    )
    assert list(r.iter_alternatives("sc")) == ["alt1.tld", "alt2.tld"]


def test_iter_alternatives_dedupes_across_sources(cache: DomainCache):
    sources = [
        _StaticSource("a", {"sc": ["dup.tld", "alt1.tld"]}),
        _StaticSource("b", {"sc": ["dup.tld", "alt2.tld"]}),
    ]
    r = DomainResolver(
        sources=sources, cache=cache,
        validator=_validator({"dup.tld", "alt1.tld", "alt2.tld"}),
        http=MagicMock(), breaker=CircuitBreaker(threshold=3),
    )
    assert list(r.iter_alternatives("sc")) == ["dup.tld", "alt1.tld", "alt2.tld"]


def test_iter_alternatives_filters_invalid_domains(cache: DomainCache):
    sources = [_StaticSource("p", {"sc": ["good.tld", "bad.tld", "also-good.tld"]})]
    r = DomainResolver(
        sources=sources, cache=cache,
        validator=_validator({"good.tld", "also-good.tld"}),
        http=MagicMock(), breaker=CircuitBreaker(threshold=3),
    )
    assert list(r.iter_alternatives("sc")) == ["good.tld", "also-good.tld"]


def test_iter_alternatives_is_lazy_can_stop_after_first(cache: DomainCache):
    """Generator nature -- caller can break after the first hit and we
    won't have validated the rest. Keeps probing cost bounded."""
    validate_calls = []
    def validator(http, domain, lang="it"):
        validate_calls.append(domain)
        return True
    sources = [_StaticSource("p", {"sc": ["a.tld", "b.tld", "c.tld"]})]
    r = DomainResolver(
        sources=sources, cache=cache, validator=validator,
        http=MagicMock(), breaker=CircuitBreaker(threshold=3),
    )
    it = r.iter_alternatives("sc")
    next(it)  # consume one
    assert validate_calls == ["a.tld"]


def test_iter_alternatives_skips_sources_that_raise(cache: DomainCache):
    bad = MagicMock()
    bad.name = "bad"
    bad.candidates.side_effect = RuntimeError("boom")
    good = _StaticSource("good", {"sc": ["alt.tld"]})
    r = DomainResolver(
        sources=[bad, good], cache=cache,
        validator=_validator({"alt.tld"}),
        http=MagicMock(), breaker=CircuitBreaker(threshold=3),
    )
    assert list(r.iter_alternatives("sc")) == ["alt.tld"]


# -- get_preferred / set_preferred --------------------------------------

def test_get_preferred_returns_none_when_unset(cache: DomainCache):
    r = DomainResolver(
        sources=[], cache=cache, validator=_validator(set()),
        http=MagicMock(), breaker=CircuitBreaker(threshold=3),
    )
    assert r.get_preferred("sc", tag="fhd") is None


def test_set_then_get_preferred_roundtrip(cache: DomainCache):
    r = DomainResolver(
        sources=[], cache=cache, validator=_validator(set()),
        http=MagicMock(), breaker=CircuitBreaker(threshold=3),
    )
    r.set_preferred("sc", tag="fhd", domain="fhd.tld")
    assert r.get_preferred("sc", tag="fhd") == "fhd.tld"


def test_preferred_cache_isolated_per_tag(cache: DomainCache):
    r = DomainResolver(
        sources=[], cache=cache, validator=_validator(set()),
        http=MagicMock(), breaker=CircuitBreaker(threshold=3),
    )
    r.set_preferred("sc", tag="fhd", domain="fhd.tld")
    r.set_preferred("sc", tag="uhd", domain="uhd.tld")
    assert r.get_preferred("sc", tag="fhd") == "fhd.tld"
    assert r.get_preferred("sc", tag="uhd") == "uhd.tld"


def test_preferred_does_not_leak_between_services(cache: DomainCache):
    r = DomainResolver(
        sources=[], cache=cache, validator=_validator(set()),
        http=MagicMock(), breaker=CircuitBreaker(threshold=3),
    )
    r.set_preferred("sc", tag="fhd", domain="fhd.tld")
    assert r.get_preferred("au", tag="fhd") is None
