"""Default async wrapper for v1 sync search()."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from streamload.models.media import MediaEntry, MediaType, ServiceCategory
from streamload.services.base import ServiceBase


class _FakeService(ServiceBase):
    name = "Fake"
    short_name = "fake"
    domains = ["example.tld"]
    category = ServiceCategory.FILM_SERIE
    language = "it"

    def search(self, query):
        return [MediaEntry(id="1", title=query, type=MediaType.FILM, url="https://x", service="fake")]

    def get_seasons(self, e): return []
    def get_episodes(self, s): return []
    def get_streams(self, i): raise NotImplementedError


@pytest.mark.asyncio
async def test_search_async_returns_same_as_sync():
    s = _FakeService(http_client=MagicMock())
    out = await s.search_async("hello")
    assert len(out) == 1
    assert out[0].title == "hello"
