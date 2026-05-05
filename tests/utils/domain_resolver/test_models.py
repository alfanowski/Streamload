from __future__ import annotations

import pytest

from streamload.utils.domain_resolver.errors import ManifestError
from streamload.utils.domain_resolver.models import (
    DomainsManifest,
    ResolvedDomain,
    ServiceDomains,
)


def test_service_domains_all_candidates_orders_primary_first():
    sd = ServiceDomains(primary="a.tld", fallbacks=["b.tld", "c.tld"])
    assert sd.all_candidates() == ["a.tld", "b.tld", "c.tld"]


def test_service_domains_dedups_fallback_equal_to_primary():
    sd = ServiceDomains(primary="a.tld", fallbacks=["a.tld", "b.tld"])
    assert sd.all_candidates() == ["a.tld", "b.tld"]


def test_manifest_from_dict_parses_minimal_payload():
    payload = {
        "schema_version": 1,
        "key_id": "sl-2026-05-53b1aa",
        "issued_at": "2026-05-05T10:00:00Z",
        "ttl_seconds": 21600,
        "services": {
            "sc": {"primary": "x.tld", "fallbacks": []},
        },
    }
    m = DomainsManifest.from_dict(payload)
    assert m.schema_version == 1
    assert m.key_id == "sl-2026-05-53b1aa"
    assert m.ttl_seconds == 21600
    assert m.services["sc"].primary == "x.tld"


def test_manifest_from_dict_rejects_unknown_schema_version():
    payload = {
        "schema_version": 999,
        "key_id": "k",
        "issued_at": "2026-05-05T10:00:00Z",
        "ttl_seconds": 1,
        "services": {},
    }
    with pytest.raises(ManifestError, match="schema_version"):
        DomainsManifest.from_dict(payload)


def test_manifest_from_dict_rejects_missing_required_field():
    payload = {"schema_version": 1, "services": {}}
    with pytest.raises(ManifestError):
        DomainsManifest.from_dict(payload)


def test_manifest_get_domains_returns_none_for_unknown_service():
    m = DomainsManifest(
        schema_version=1,
        key_id="k",
        issued_at="2026-05-05T10:00:00Z",
        ttl_seconds=1,
        services={},
    )
    assert m.get_domains("sc") is None


def test_resolved_domain_carries_source_tag():
    rd = ResolvedDomain(domain="x.tld", source="cache", validated_at=123.0)
    assert rd.domain == "x.tld"
    assert rd.source == "cache"
