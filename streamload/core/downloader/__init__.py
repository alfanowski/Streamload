"""Download engines for Streamload.

Re-exports the three concrete downloaders and the abstract base class
so consumers can import directly from the package::

    from streamload.core.downloader import HLSDownloader, DASHDownloader, MP4Downloader
"""

from streamload.core.downloader.base import BaseDownloader
from streamload.core.downloader.dash import DASHDownloader
from streamload.core.downloader.hls import HLSDownloader
from streamload.core.downloader.mp4 import MP4Downloader

__all__ = [
    "BaseDownloader",
    "DASHDownloader",
    "HLSDownloader",
    "MP4Downloader",
]
