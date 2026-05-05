from streamload.utils.domain_resolver.sources.discovery_source import DiscoverySource


def test_returns_empty_for_unknown_service():
    src = DiscoverySource(seeds={})
    assert src.candidates("sc") == []


def test_returns_empty_for_service_without_prefixes_or_tlds():
    src = DiscoverySource(seeds={"sc": {}})
    assert src.candidates("sc") == []


def test_generates_full_cartesian_product():
    src = DiscoverySource(seeds={
        "sc": {"prefixes": ["a", "b"], "tlds": ["x", "y"]},
    })
    assert src.candidates("sc") == ["a.x", "a.y", "b.x", "b.y"]


def test_dedupes_when_prefixes_or_tlds_repeat():
    src = DiscoverySource(seeds={
        "sc": {"prefixes": ["a", "a"], "tlds": ["x", "x"]},
    })
    assert src.candidates("sc") == ["a.x"]


def test_skips_blank_prefix_or_tld():
    src = DiscoverySource(seeds={
        "sc": {"prefixes": ["", "a"], "tlds": ["x", ""]},
    })
    assert src.candidates("sc") == ["a.x"]


def test_name():
    assert DiscoverySource(seeds={}).name == "discovery"
