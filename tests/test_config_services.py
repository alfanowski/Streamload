from streamload.models.config import AppConfig


def test_services_section_defaults_to_empty_dict():
    cfg = AppConfig.from_dict({})
    assert cfg.services == {}


def test_services_section_parses_overrides():
    cfg = AppConfig.from_dict({
        "services": {"sc": {"base_url": "https://my.tld"}},
    })
    assert cfg.services == {"sc": {"base_url": "https://my.tld"}}


def test_services_section_ignores_non_dict():
    cfg = AppConfig.from_dict({"services": "garbage"})
    assert cfg.services == {}
