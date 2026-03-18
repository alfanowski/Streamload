"""Abstract base downloader for Streamload.

Defines the contract that every download engine (HLS, DASH, MP4) must
fulfil.  Concrete implementations live in sibling modules and are
re-exported from the package ``__init__``.

The base class is intentionally thin -- it holds the two universal
dependencies (*http_client* and *config*) and exposes a single
``download()`` entry-point that subclasses implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from streamload.core.events import EventCallbacks
from streamload.models.config import DownloadConfig
from streamload.models.stream import SelectedTracks
from streamload.utils.http import HttpClient


class BaseDownloader(ABC):
    """Abstract base for download engines (HLS, DASH, MP4).

    Parameters
    ----------
    http_client:
        Shared HTTP client instance used for all network requests.
    config:
        Download-engine tunables (thread count, retry count, etc.).
    """

    def __init__(self, http_client: HttpClient, config: DownloadConfig) -> None:
        self._http = http_client
        self._config = config

    @abstractmethod
    def download(
        self,
        download_id: str,
        tracks: SelectedTracks,
        output_dir: Path,
        callbacks: EventCallbacks,
    ) -> list[Path]:
        """Download selected tracks to *output_dir*.

        Returns a list of downloaded file paths (video, audio, and
        subtitle files).  Must call ``callbacks.on_progress()``
        regularly so the frontend can display progress.

        Parameters
        ----------
        download_id:
            Unique identifier for this download task.
        tracks:
            The user's final track selection.
        output_dir:
            Directory where downloaded files are written.
        callbacks:
            Event interface for progress reporting.
        """
        ...

    def _generate_temp_filename(
        self, download_id: str, track_type: str, ext: str,
    ) -> str:
        """Generate a temp filename like ``'dl_abc123_video.ts'``.

        Parameters
        ----------
        download_id:
            Unique download identifier (used as part of the name).
        track_type:
            Descriptive label -- ``"video"``, ``"audio_ita"``, etc.
        ext:
            File extension without the leading dot.
        """
        return f"dl_{download_id}_{track_type}.{ext}"
