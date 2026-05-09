import pytest
from unittest.mock import AsyncMock, MagicMock

from streamload.streaming.fetcher import SegmentFetcher


def _ok(bytes_: bytes):
    r = MagicMock()
    r.status_code = 200
    r.content = bytes_
    r.raise_for_status = MagicMock()
    return r


@pytest.mark.asyncio
async def test_fetch_hits_ram_cache_first():
    http = MagicMock()
    http.get = AsyncMock(return_value=_ok(b"upstream"))
    ram = MagicMock()
    ram.get = MagicMock(return_value=b"ram-hit")
    disk = MagicMock()
    f = SegmentFetcher(http=http, ram=ram, disk=disk)
    out = await f.fetch("k", upstream_url="https://x", headers={})
    assert out == b"ram-hit"
    http.get.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_falls_through_to_disk():
    http = MagicMock()
    http.get = AsyncMock()
    ram = MagicMock()
    ram.get = MagicMock(return_value=None)
    ram.set = MagicMock()
    disk = MagicMock()
    disk.get = MagicMock(return_value=b"disk-hit")
    f = SegmentFetcher(http=http, ram=ram, disk=disk)
    out = await f.fetch("k", upstream_url="https://x", headers={})
    assert out == b"disk-hit"
    ram.set.assert_called_once_with("k", b"disk-hit")
    http.get.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_misses_both_caches_goes_upstream():
    http = MagicMock()
    http.get = AsyncMock(return_value=_ok(b"upstream-bytes"))
    ram = MagicMock(); ram.get = MagicMock(return_value=None); ram.set = MagicMock()
    disk = MagicMock(); disk.get = MagicMock(return_value=None); disk.set = MagicMock()
    f = SegmentFetcher(http=http, ram=ram, disk=disk)
    out = await f.fetch("k", upstream_url="https://x", headers={"Referer": "r"})
    assert out == b"upstream-bytes"
    ram.set.assert_called_once_with("k", b"upstream-bytes")
    disk.set.assert_called_once()
    http.get.assert_called_once_with("https://x", headers={"Referer": "r"})


@pytest.mark.asyncio
async def test_fetch_decrypts_when_decryptor_provided():
    http = MagicMock(); http.get = AsyncMock(return_value=_ok(b"encrypted"))
    ram = MagicMock(); ram.get = MagicMock(return_value=None); ram.set = MagicMock()
    disk = MagicMock(); disk.get = MagicMock(return_value=None); disk.set = MagicMock()
    decryptor = MagicMock(return_value=b"plaintext")
    f = SegmentFetcher(http=http, ram=ram, disk=disk, decryptor=decryptor)
    out = await f.fetch("k", upstream_url="https://x", headers={})
    assert out == b"plaintext"
    decryptor.assert_called_once_with(b"encrypted")
    # The cached value is the *decrypted* one (we never want to re-decrypt)
    ram.set.assert_called_once_with("k", b"plaintext")
