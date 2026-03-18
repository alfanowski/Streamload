"""Manifest parsing and stream selection for Streamload.

Re-exports the HLS/DASH parsers and the stream selector so that
consumers can import directly from the package::

    from streamload.core.manifest import M3U8Parser, MPDParser, StreamSelector
"""

from streamload.core.manifest.m3u8 import M3U8Parser, M3U8Playlist, M3U8Segment
from streamload.core.manifest.mpd import DASHRepresentation, DASHSegment, MPDParser
from streamload.core.manifest.stream import StreamSelector

__all__ = [
    "DASHRepresentation",
    "DASHSegment",
    "M3U8Parser",
    "M3U8Playlist",
    "M3U8Segment",
    "MPDParser",
    "StreamSelector",
]
