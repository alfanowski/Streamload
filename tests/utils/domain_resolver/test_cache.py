from __future__ import annotations

import json
from pathlib import Path

import pytest

from streamload.utils.domain_resolver.cache import DomainCache


@pytest.fixture
def cache(tmp_path: Path) -> DomainCache:
    return DomainCache(tmp_path / "domains_cache.json")


def test_get_returns_none_when_file_absent(cache: DomainCache):
    assert cache.get("sc") is None


def test_set_then_get_roundtrip(cache: DomainCache):
    cache.set("sc", domain="x.tld", source="remote-github", validated_at=100.0)
    entry = cache.get("sc")
    assert entry is not None
    assert entry["domain"] == "x.tld"
    assert entry["source"] == "remote-github"
    assert entry["validated_at"] == 100.0


def test_set_persists_atomically(cache: DomainCache, tmp_path: Path):
    cache.set("sc", domain="x.tld", source="cache", validated_at=1.0)
    raw = json.loads((tmp_path / "domains_cache.json").read_text())
    assert raw["entries"]["sc"]["domain"] == "x.tld"


def test_invalidate_removes_entry(cache: DomainCache):
    cache.set("sc", domain="x.tld", source="cache", validated_at=1.0)
    cache.invalidate("sc")
    assert cache.get("sc") is None


def test_invalidate_unknown_service_is_noop(cache: DomainCache):
    cache.invalidate("nope")  # must not raise


def test_corrupt_cache_file_is_treated_as_empty(cache: DomainCache, tmp_path: Path):
    (tmp_path / "domains_cache.json").write_text("{not json")
    assert cache.get("sc") is None


def test_is_fresh_uses_validated_at_and_ttl(cache: DomainCache):
    cache.set("sc", domain="x.tld", source="cache", validated_at=1000.0)
    assert cache.is_fresh("sc", ttl_seconds=10, now=1005.0) is True
    assert cache.is_fresh("sc", ttl_seconds=10, now=1011.0) is False
    assert cache.is_fresh("missing", ttl_seconds=10, now=1000.0) is False
