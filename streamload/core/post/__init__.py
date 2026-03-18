"""Post-processing pipeline for Streamload.

Re-exports the merge, subtitle conversion, and metadata generation
components so consumers can import directly from the package::

    from streamload.core.post import FFmpegMerger, SubtitleConverter, NFOGenerator
"""

from streamload.core.post.merge import FFmpegMerger
from streamload.core.post.metadata import NFOGenerator
from streamload.core.post.subtitles import SubtitleConverter

__all__ = [
    "FFmpegMerger",
    "NFOGenerator",
    "SubtitleConverter",
]
