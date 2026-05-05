from __future__ import annotations

from unittest.mock import MagicMock

from streamload.models.media import ServiceCategory
from streamload.services.base import ServiceBase


class _Dummy(ServiceBase):
    name = "Dummy"
    short_name = "dummy"
    domains = ["seed.tld"]
    category = ServiceCategory.FILM_SERIE
    language = "it"

    def search(self, q): return []
    def get_seasons(self, e): return []
    def get_episodes(self, s): return []
    def get_streams(self, i): raise NotImplementedError


def test_base_url_falls_back_to_first_domain_when_no_resolver():
    s = _Dummy(http_client=MagicMock())
    assert s.base_url == "https://seed.tld"


def test_base_url_uses_resolver_when_attached():
    s = _Dummy(http_client=MagicMock())
    resolver = MagicMock()
    resolver.resolve.return_value = MagicMock(domain="resolved.tld")
    s.attach_resolver(resolver)
    assert s.base_url == "https://resolved.tld"
    resolver.resolve.assert_called_once_with("dummy")


def test_base_url_caches_resolved_domain_per_instance():
    s = _Dummy(http_client=MagicMock())
    resolver = MagicMock()
    resolver.resolve.return_value = MagicMock(domain="resolved.tld")
    s.attach_resolver(resolver)
    _ = s.base_url
    _ = s.base_url
    resolver.resolve.assert_called_once()
