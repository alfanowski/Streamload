"""Streamload CLI UI components.

Re-exports every public class and formatting function so consumers
can write::

    from streamload.cli.ui import DownloadProgressUI, UIPrompts
    from streamload.cli.ui import format_search_result, format_episode
"""

from streamload.cli.ui.progress import DownloadProgressUI
from streamload.cli.ui.prompts import UIPrompts
from streamload.cli.ui.selector import InteractiveSelector
from streamload.cli.ui.tables import (
    format_audio_track,
    format_episode,
    format_search_result,
    format_season,
    format_service,
    format_subtitle_track,
    format_video_track,
)

__all__ = [
    "DownloadProgressUI",
    "InteractiveSelector",
    "UIPrompts",
    "format_audio_track",
    "format_episode",
    "format_search_result",
    "format_season",
    "format_service",
    "format_subtitle_track",
    "format_video_track",
]
