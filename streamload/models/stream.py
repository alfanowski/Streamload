"""Stream track and bundle models for Streamload.

Defines the data structures produced by manifest parsers and consumed
by the download engine: video/audio/subtitle tracks, DRM metadata,
and the user's final track selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VideoTrack:
    """A single video variant from a manifest."""

    id: str
    resolution: str  # "1920x1080"
    codec: str  # "h264", "h265", "av1"
    bitrate: int | None = None  # bps
    fps: float | None = None
    hdr: bool = False

    @property
    def height(self) -> int:
        """Extract height from resolution string (e.g. 1080 from '1920x1080')."""
        try:
            return int(self.resolution.split("x")[1])
        except (IndexError, ValueError):
            return 0

    @property
    def label(self) -> str:
        """Human-readable label like '1080p h264' or '2160p h265 HDR'."""
        h = self.height
        p = f"{h}p" if h else self.resolution
        return f"{p} {self.codec}" + (" HDR" if self.hdr else "")


@dataclass
class AudioTrack:
    """A single audio variant from a manifest."""

    id: str
    language: str  # ISO 639 code: "ita", "eng"
    codec: str  # "aac", "opus", "eac3"
    channels: str = "2.0"  # "2.0", "5.1"
    bitrate: int | None = None
    name: str | None = None  # display name from manifest

    @property
    def label(self) -> str:
        """Human-readable label like 'ita aac 5.1'."""
        return f"{self.language} {self.codec} {self.channels}"


@dataclass
class SubtitleTrack:
    """A single subtitle variant from a manifest."""

    id: str
    language: str  # ISO 639 code
    format: str = "vtt"  # "srt", "vtt", "ass"
    forced: bool = False
    name: str | None = None

    @property
    def label(self) -> str:
        """Human-readable label like 'eng vtt' or 'ita srt [forced]'."""
        forced_tag = " [forced]" if self.forced else ""
        return f"{self.language} {self.format}{forced_tag}"


@dataclass
class StreamBundle:
    """All available tracks for a single piece of content, plus DRM info.

    Produced by ``ServiceBase.get_streams()`` and consumed by the track
    selection UI and the download engine.
    """

    video: list[VideoTrack] = field(default_factory=list)
    audio: list[AudioTrack] = field(default_factory=list)
    subtitles: list[SubtitleTrack] = field(default_factory=list)
    drm_type: str | None = None  # "widevine" | "playready" | None
    pssh: str | None = None  # PSSH box if DRM (base64)
    license_url: str | None = None  # License server URL if DRM
    manifest_url: str | None = None  # Original manifest URL


@dataclass
class SelectedTracks:
    """The user's final track choices, ready for download.

    Exactly one video track, zero-or-more audio tracks, and
    zero-or-more subtitle tracks.
    """

    video: VideoTrack
    audio: list[AudioTrack] = field(default_factory=list)
    subtitles: list[SubtitleTrack] = field(default_factory=list)
