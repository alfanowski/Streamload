"""Tests for quality auto-probe of master playlist."""
from streamload.streaming.quality_probe import max_height_from_master


def test_extracts_max_resolution():
    master = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=854x480\nhttps://x/480p\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=2150000,RESOLUTION=1280x720\nhttps://x/720p\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=4500000,RESOLUTION=1920x1080\nhttps://x/1080p\n"
    )
    assert max_height_from_master(master) == 1080


def test_returns_none_when_no_resolution():
    master = "#EXTM3U\n#EXT-X-VERSION:3\n"
    assert max_height_from_master(master) is None
