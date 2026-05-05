from streamload.utils.domain_resolver.sources.config_source import ConfigSource


def test_returns_none_when_no_override():
    src = ConfigSource(overrides={})
    assert src.candidates("sc") == []


def test_returns_override_when_present():
    src = ConfigSource(overrides={"sc": "my.tld"})
    assert src.candidates("sc") == ["my.tld"]


def test_strips_protocol_and_path_from_override():
    src = ConfigSource(overrides={"sc": "https://my.tld/it/"})
    assert src.candidates("sc") == ["my.tld"]


def test_ignores_blank_override():
    src = ConfigSource(overrides={"sc": "  "})
    assert src.candidates("sc") == []


def test_name():
    assert ConfigSource(overrides={}).name == "config"
