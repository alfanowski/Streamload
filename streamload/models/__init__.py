"""Shared data models for Streamload.

Re-exports every public type so consumers can write::

    from streamload.models import MediaEntry, StreamBundle, AppConfig
"""

from streamload.models.config import (
    AppConfig,
    DownloadConfig,
    DRMConfig,
    DRMDeviceConfig,
    NetworkConfig,
    OutputConfig,
    ProcessConfig,
)
from streamload.models.media import (
    AuthSession,
    Episode,
    MediaEntry,
    MediaType,
    SearchResult,
    Season,
    ServiceCategory,
)
from streamload.models.stream import (
    AudioTrack,
    SelectedTracks,
    StreamBundle,
    SubtitleTrack,
    VideoTrack,
)

__all__ = [
    # media.py
    "AuthSession",
    "Episode",
    "MediaEntry",
    "MediaType",
    "SearchResult",
    "Season",
    "ServiceCategory",
    # stream.py
    "AudioTrack",
    "SelectedTracks",
    "StreamBundle",
    "SubtitleTrack",
    "VideoTrack",
    # config.py
    "AppConfig",
    "DownloadConfig",
    "DRMConfig",
    "DRMDeviceConfig",
    "NetworkConfig",
    "OutputConfig",
    "ProcessConfig",
]
