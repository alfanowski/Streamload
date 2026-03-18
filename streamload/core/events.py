"""Event system for core-to-CLI communication.

The core library never prints to the console.  Instead it emits typed
event objects that the CLI layer (or any other frontend) receives through
the :class:`EventCallbacks` interface and decides how to present.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from streamload.core.exceptions import StreamloadError
from streamload.models.stream import (
    AudioTrack,
    SelectedTracks,
    SubtitleTrack,
    VideoTrack,
)


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DownloadProgress:
    """Periodic progress update for an in-flight download.

    Attributes
    ----------
    download_id:
        Unique identifier for this download task.
    filename:
        Display name of the file being downloaded.
    downloaded:
        Number of bytes received so far.
    total:
        Total expected size in bytes (``0`` when unknown).
    speed:
        Current transfer rate in bytes per second.
    """

    download_id: str
    filename: str
    downloaded: int
    total: int
    speed: float  # bytes/sec


@dataclass(frozen=True)
class TrackSelection:
    """Available tracks presented to the user for selection.

    The callback must return a :class:`SelectedTracks` with the user's
    choices.
    """

    video_tracks: list[VideoTrack] = field(default_factory=list)
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    subtitle_tracks: list[SubtitleTrack] = field(default_factory=list)


@dataclass(frozen=True)
class DownloadComplete:
    """Emitted when a download (including post-processing) finishes.

    Attributes
    ----------
    download_id:
        Matches the ``download_id`` from earlier progress events.
    filepath:
        Absolute path to the final output file on disk.
    duration:
        Wall-clock seconds the download took.
    size:
        Final file size in bytes.
    """

    download_id: str
    filepath: Path
    duration: float
    size: int


@dataclass(frozen=True)
class ErrorEvent:
    """An error that occurred during processing.

    Attributes
    ----------
    download_id:
        Identifier of the affected download, or ``None`` if the error
        is not tied to a specific download (e.g. a config problem).
    error:
        The underlying exception.
    message:
        Human-readable summary.
    recoverable:
        ``True`` when the operation can be retried or skipped.
    """

    download_id: str | None
    error: StreamloadError
    message: str
    recoverable: bool


@dataclass(frozen=True)
class WarningEvent:
    """A non-fatal warning the user should be aware of.

    Attributes
    ----------
    message:
        Human-readable description of the issue.
    context:
        Optional extra detail (e.g. the file or URL involved).
    """

    message: str
    context: str | None = None


@dataclass(frozen=True)
class MergeProgress:
    """Emitted during post-download merge / conversion stages.

    Attributes
    ----------
    download_id:
        Identifier of the affected download.
    filename:
        Display name of the file being processed.
    stage:
        Current stage label: ``"merging"``,
        ``"converting_subtitles"``, or ``"generating_nfo"``.
    """

    download_id: str
    filename: str
    stage: str  # "merging" | "converting_subtitles" | "generating_nfo"


@dataclass(frozen=True)
class SearchProgress:
    """Emitted while searching a service catalogue.

    Attributes
    ----------
    service_name:
        Identifier of the service being searched.
    status:
        Current phase: ``"searching"``, ``"done"``, or ``"error"``.
    results_count:
        Number of results found so far.
    """

    service_name: str
    status: str  # "searching" | "done" | "error"
    results_count: int = 0


# ---------------------------------------------------------------------------
# Abstract callback interface
# ---------------------------------------------------------------------------


class EventCallbacks(ABC):
    """Interface that frontends implement to receive core events.

    The core engine holds a reference to an ``EventCallbacks`` instance
    and calls the appropriate method whenever a noteworthy event occurs.
    """

    @abstractmethod
    def on_track_selection(self, event: TrackSelection) -> SelectedTracks:
        """Present available tracks and return the user's selection."""

    @abstractmethod
    def on_progress(self, event: DownloadProgress) -> None:
        """Handle a download-progress update."""

    @abstractmethod
    def on_complete(self, event: DownloadComplete) -> None:
        """Handle download completion."""

    @abstractmethod
    def on_error(self, event: ErrorEvent) -> None:
        """Handle an error event."""

    @abstractmethod
    def on_warning(self, event: WarningEvent) -> None:
        """Handle a warning event."""

    @abstractmethod
    def on_merge_progress(self, event: MergeProgress) -> None:
        """Handle a merge/post-processing progress update."""

    @abstractmethod
    def on_search_progress(self, event: SearchProgress) -> None:
        """Handle a search-progress update."""
