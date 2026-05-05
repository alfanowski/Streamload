from streamload.utils.domain_resolver.sources.probe_source import ProbeSource


def test_returns_seed_list_for_known_service():
    src = ProbeSource(seeds={"sc": ["a.tld", "b.tld"]})
    assert src.candidates("sc") == ["a.tld", "b.tld"]


def test_returns_empty_for_unknown_service():
    src = ProbeSource(seeds={})
    assert src.candidates("sc") == []


def test_name():
    assert ProbeSource(seeds={}).name == "probe"
