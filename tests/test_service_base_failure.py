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


def test_report_domain_failure_is_noop_without_resolver():
    s = _Dummy(http_client=MagicMock())
    s.report_domain_failure()  # must not raise


def test_report_domain_failure_calls_resolver_and_resets_cache():
    s = _Dummy(http_client=MagicMock())
    resolver = MagicMock()
    resolver.resolve.return_value = MagicMock(domain="x.tld")
    s.attach_resolver(resolver)
    _ = s.base_url  # populate _resolved_domain cache
    s.report_domain_failure()
    resolver.record_failure.assert_called_once_with("dummy")
    # Next base_url read should re-resolve
    resolver.resolve.return_value = MagicMock(domain="y.tld")
    assert s.base_url == "https://y.tld"
