"""Disk LRU segment cache."""
import pytest
from pathlib import Path

from streamload.streaming.disk_cache import SegmentCache


def test_set_then_get_roundtrip(tmp_path: Path):
    c = SegmentCache(directory=str(tmp_path), size_limit_bytes=10*1024*1024)
    c.set("k1", b"hello world")
    assert c.get("k1") == b"hello world"


def test_get_missing_returns_none(tmp_path: Path):
    c = SegmentCache(directory=str(tmp_path), size_limit_bytes=10*1024*1024)
    assert c.get("k_missing") is None


def test_lru_evicts_when_full(tmp_path: Path):
    c = SegmentCache(directory=str(tmp_path), size_limit_bytes=200)  # tiny
    c.set("a", b"a" * 100)
    c.set("b", b"b" * 100)
    c.set("c", b"c" * 100)  # forces eviction
    # Some keys evicted; total below limit
    keys_present = [k for k in ("a", "b", "c") if c.get(k) is not None]
    assert len(keys_present) <= 2


def test_clear(tmp_path: Path):
    c = SegmentCache(directory=str(tmp_path), size_limit_bytes=10*1024*1024)
    c.set("x", b"y")
    c.clear()
    assert c.get("x") is None
