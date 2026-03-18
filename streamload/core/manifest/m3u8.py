"""HLS M3U8 manifest parser for Streamload.

Parses both master playlists (multi-variant streams) and media playlists
(segment lists) without any third-party dependencies.  The parser is
intentionally lenient: unknown tags are silently skipped so that new HLS
extensions never cause hard failures.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from streamload.models.stream import (
    AudioTrack,
    StreamBundle,
    SubtitleTrack,
    VideoTrack,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models local to HLS parsing
# ---------------------------------------------------------------------------


@dataclass
class M3U8Segment:
    """A single media segment in an HLS media playlist."""

    url: str
    duration: float
    key_url: str | None = None
    key_iv: str | None = None
    key_method: str | None = None  # "AES-128", "SAMPLE-AES", "NONE"
    byterange: tuple[int, int] | None = None  # (length, offset)


@dataclass
class M3U8Playlist:
    """Parsed result of an HLS media playlist."""

    segments: list[M3U8Segment] = field(default_factory=list)
    total_duration: float = 0.0
    is_master: bool = False
    target_duration: float = 0.0
    init_url: str | None = None  # EXT-X-MAP URI


# ---------------------------------------------------------------------------
# Attribute-string regex
# ---------------------------------------------------------------------------

# Matches KEY=VALUE pairs where VALUE is either a quoted string or an
# unquoted token.  Handles commas inside quoted strings correctly and
# also handles values that contain commas within double quotes (e.g.
# CODECS="avc1.640028,mp4a.40.2").
_ATTR_RE = re.compile(
    r"""(?P<key>[A-Z0-9_-]+)=(?:"(?P<qval>[^"]*)"|(?P<val>[^,]*))""",
    re.ASCII,
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class M3U8Parser:
    """Parse HLS m3u8 manifests into structured data.

    Usage::

        parser = M3U8Parser()

        # Master playlist -> StreamBundle with available tracks
        bundle = parser.parse_master(master_text, master_url)

        # Media playlist -> M3U8Playlist with segment list
        playlist = parser.parse_media(media_text, media_url)
    """

    # -- Public API ---------------------------------------------------------

    def parse_master(self, content: str, base_url: str) -> StreamBundle:
        """Parse a master playlist and extract all available tracks.

        Parameters
        ----------
        content:
            Raw text of the m3u8 master playlist.
        base_url:
            URL the playlist was fetched from, used to resolve relative URIs.

        Returns
        -------
        StreamBundle:
            Populated ``video``, ``audio``, and ``subtitles`` lists.
            The ``id`` field of each :class:`VideoTrack` stores the absolute
            media-playlist URL so the caller can fetch segments later.
        """
        if not self._is_m3u8(content):
            log.warning("Content does not start with #EXTM3U -- attempting parse anyway")

        video_tracks: list[VideoTrack] = []
        audio_tracks: list[AudioTrack] = []
        subtitle_tracks: list[SubtitleTrack] = []

        # First pass: collect #EXT-X-MEDIA renditions (audio / subtitles).
        # We need these *before* processing STREAM-INF because video variants
        # reference audio groups by GROUP-ID.
        audio_groups: dict[str, list[AudioTrack]] = {}
        subtitle_groups: dict[str, list[SubtitleTrack]] = {}

        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#EXT-X-MEDIA:"):
                attrs = self._parse_attributes(line.split(":", 1)[1])
                media_type = attrs.get("TYPE", "")
                if media_type == "AUDIO":
                    track = self._parse_audio_media(attrs, base_url)
                    audio_tracks.append(track)
                    group_id = attrs.get("GROUP-ID", "")
                    audio_groups.setdefault(group_id, []).append(track)
                elif media_type == "SUBTITLES":
                    track = self._parse_subtitle_media(attrs, base_url)
                    subtitle_tracks.append(track)
                    group_id = attrs.get("GROUP-ID", "")
                    subtitle_groups.setdefault(group_id, []).append(track)

        # Second pass: collect #EXT-X-STREAM-INF video variants.
        lines = content.splitlines()
        idx = 0
        variant_counter = 0
        while idx < len(lines):
            line = lines[idx].strip()
            if line.startswith("#EXT-X-STREAM-INF:"):
                attrs = self._parse_attributes(line.split(":", 1)[1])
                # The URI is on the next non-empty, non-comment line.
                uri = self._next_uri(lines, idx + 1)
                if uri is not None:
                    track = self._parse_stream_inf(
                        attrs, uri, base_url, variant_counter,
                    )
                    video_tracks.append(track)
                    variant_counter += 1
            idx += 1

        return StreamBundle(
            video=video_tracks,
            audio=audio_tracks,
            subtitles=subtitle_tracks,
        )

    def parse_media(self, content: str, base_url: str) -> M3U8Playlist:
        """Parse a media playlist and extract segments.

        Parameters
        ----------
        content:
            Raw text of the media playlist.
        base_url:
            URL the playlist was fetched from, used to resolve relative URIs.

        Returns
        -------
        M3U8Playlist:
            Ordered list of :class:`M3U8Segment` objects ready for download.
        """
        if not self._is_m3u8(content):
            log.warning("Content does not start with #EXTM3U -- attempting parse anyway")

        playlist = M3U8Playlist()
        lines = content.splitlines()

        # Current encryption state -- inherited by segments until changed.
        cur_key_method: str | None = None
        cur_key_url: str | None = None
        cur_key_iv: str | None = None

        # Pending EXTINF / byterange to attach to the next segment URI.
        pending_duration: float | None = None
        pending_byterange: tuple[int, int] | None = None
        last_byterange_offset: int = 0

        for line in lines:
            line = line.strip()

            if not line or line.startswith("#EXTM3U"):
                continue

            # ----- Target duration -----
            if line.startswith("#EXT-X-TARGETDURATION:"):
                try:
                    playlist.target_duration = float(line.split(":")[1])
                except (IndexError, ValueError):
                    pass
                continue

            # ----- Encryption key -----
            if line.startswith("#EXT-X-KEY:"):
                attrs = self._parse_attributes(line.split(":", 1)[1])
                cur_key_method = attrs.get("METHOD", "NONE")
                if cur_key_method == "NONE":
                    cur_key_url = None
                    cur_key_iv = None
                else:
                    key_uri = attrs.get("URI", "")
                    cur_key_url = self._resolve_url(key_uri, base_url) if key_uri else None
                    cur_key_iv = attrs.get("IV")
                continue

            # ----- Init segment (EXT-X-MAP) -----
            if line.startswith("#EXT-X-MAP:"):
                attrs = self._parse_attributes(line.split(":", 1)[1])
                map_uri = attrs.get("URI", "")
                if map_uri:
                    playlist.init_url = self._resolve_url(map_uri, base_url)
                continue

            # ----- Byte range -----
            if line.startswith("#EXT-X-BYTERANGE:"):
                pending_byterange = self._parse_byterange(
                    line.split(":")[1], last_byterange_offset,
                )
                continue

            # ----- Segment duration -----
            if line.startswith("#EXTINF:"):
                raw = line.split(":")[1]
                # Duration may be followed by a comma and optional title.
                dur_str = raw.split(",")[0]
                try:
                    pending_duration = float(dur_str)
                except ValueError:
                    pending_duration = 0.0
                continue

            # ----- Master-playlist indicator (skip) -----
            if line.startswith("#EXT-X-STREAM-INF"):
                playlist.is_master = True
                continue

            # ----- Ignore other tags -----
            if line.startswith("#"):
                continue

            # ----- Segment URI line -----
            if pending_duration is not None:
                url = self._resolve_url(line, base_url)
                segment = M3U8Segment(
                    url=url,
                    duration=pending_duration,
                    key_url=cur_key_url,
                    key_iv=cur_key_iv,
                    key_method=cur_key_method if cur_key_method != "NONE" else None,
                    byterange=pending_byterange,
                )
                playlist.segments.append(segment)
                playlist.total_duration += pending_duration

                # Update running byte-range offset for consecutive ranges.
                if pending_byterange is not None:
                    length, offset = pending_byterange
                    last_byterange_offset = offset + length
                pending_duration = None
                pending_byterange = None

        return playlist

    # -- URL resolution -----------------------------------------------------

    def _resolve_url(self, url: str, base_url: str) -> str:
        """Resolve a potentially relative URL against *base_url*.

        Absolute URLs (starting with ``http://`` or ``https://``) and
        data URIs are returned unchanged.  Everything else is resolved
        with :func:`urllib.parse.urljoin`.
        """
        if url.startswith(("http://", "https://", "data:")):
            return url
        return urljoin(base_url, url)

    # -- Attribute parsing --------------------------------------------------

    def _parse_attributes(self, attr_string: str) -> dict[str, str]:
        """Parse an M3U8 attribute list into a ``{KEY: value}`` dict.

        Both quoted (``KEY="value"``) and unquoted (``KEY=value``) forms
        are handled.  Keys are normalised to uppercase.
        """
        result: dict[str, str] = {}
        for m in _ATTR_RE.finditer(attr_string):
            key = m.group("key").upper()
            value = m.group("qval") if m.group("qval") is not None else m.group("val")
            result[key] = value
        return result

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _is_m3u8(content: str) -> bool:
        """Return ``True`` if *content* looks like an M3U8 playlist."""
        return content.lstrip().startswith("#EXTM3U")

    @staticmethod
    def _next_uri(lines: list[str], start: int) -> str | None:
        """Return the next non-empty, non-comment line starting at *start*."""
        for i in range(start, len(lines)):
            candidate = lines[i].strip()
            if candidate and not candidate.startswith("#"):
                return candidate
        return None

    def _parse_stream_inf(
        self,
        attrs: dict[str, str],
        uri: str,
        base_url: str,
        index: int,
    ) -> VideoTrack:
        """Build a :class:`VideoTrack` from ``#EXT-X-STREAM-INF`` attributes."""
        resolved_url = self._resolve_url(uri, base_url)

        # Resolution (e.g. "1920x1080").
        resolution = attrs.get("RESOLUTION", "0x0")

        # Bandwidth in bits/s.
        bandwidth: int | None = None
        bw_str = attrs.get("BANDWIDTH", attrs.get("AVERAGE-BANDWIDTH"))
        if bw_str is not None:
            try:
                bandwidth = int(bw_str)
            except ValueError:
                pass

        # Codecs -- extract the video codec portion.
        codecs_str = attrs.get("CODECS", "")
        codec = self._extract_video_codec(codecs_str)

        # Frame rate.
        fps: float | None = None
        fps_str = attrs.get("FRAME-RATE")
        if fps_str is not None:
            try:
                fps = float(fps_str)
            except ValueError:
                pass

        # HDR flag.
        video_range = attrs.get("VIDEO-RANGE", "SDR").upper()
        hdr = video_range != "SDR"

        return VideoTrack(
            id=resolved_url,
            resolution=resolution,
            codec=codec,
            bitrate=bandwidth,
            fps=fps,
            hdr=hdr,
        )

    def _parse_audio_media(
        self, attrs: dict[str, str], base_url: str,
    ) -> AudioTrack:
        """Build an :class:`AudioTrack` from ``#EXT-X-MEDIA TYPE=AUDIO``."""
        uri = attrs.get("URI", "")
        resolved_url = self._resolve_url(uri, base_url) if uri else ""

        language = attrs.get("LANGUAGE", "und")
        name = attrs.get("NAME")
        group_id = attrs.get("GROUP-ID", "")

        # Channel count -- "2", "6", "8" etc.
        channels_raw = attrs.get("CHANNELS", "2")
        # The first value before '/' is the channel count.
        try:
            ch_count = int(channels_raw.split("/")[0])
        except ValueError:
            ch_count = 2
        channels = self._channel_label(ch_count)

        # We cannot determine the audio codec from #EXT-X-MEDIA alone;
        # it comes from the CODECS attribute on the STREAM-INF line.
        # Default to "aac" as that is overwhelmingly common for HLS.
        codec = "aac"

        track_id = resolved_url if resolved_url else f"audio-{group_id}-{language}"

        return AudioTrack(
            id=track_id,
            language=language,
            codec=codec,
            channels=channels,
            name=name,
        )

    def _parse_subtitle_media(
        self, attrs: dict[str, str], base_url: str,
    ) -> SubtitleTrack:
        """Build a :class:`SubtitleTrack` from ``#EXT-X-MEDIA TYPE=SUBTITLES``."""
        uri = attrs.get("URI", "")
        resolved_url = self._resolve_url(uri, base_url) if uri else ""

        language = attrs.get("LANGUAGE", "und")
        name = attrs.get("NAME")
        group_id = attrs.get("GROUP-ID", "")
        forced = attrs.get("FORCED", "NO").upper() == "YES"

        track_id = resolved_url if resolved_url else f"sub-{group_id}-{language}"

        return SubtitleTrack(
            id=track_id,
            language=language,
            format="vtt",  # HLS subtitles are almost always WebVTT.
            forced=forced,
            name=name,
        )

    @staticmethod
    def _parse_byterange(value: str, last_offset: int) -> tuple[int, int]:
        """Parse an ``EXT-X-BYTERANGE`` value like ``1024`` or ``1024@0``.

        Returns ``(length, offset)``.  When the offset is omitted it
        defaults to *last_offset* (the byte after the previous range).
        """
        value = value.strip()
        if "@" in value:
            parts = value.split("@", 1)
            return int(parts[0]), int(parts[1])
        return int(value), last_offset

    @staticmethod
    def _extract_video_codec(codecs_str: str) -> str:
        """Extract a human-friendly video codec name from a CODECS string.

        ``"avc1.640028,mp4a.40.2"`` -> ``"h264"``
        ``"hvc1.1.6.L150.90"``      -> ``"h265"``
        ``"av01.0.12M.10"``         -> ``"av1"``
        ``"vp09.00.50.08"``         -> ``"vp9"``
        """
        codecs = codecs_str.lower()
        if "avc1" in codecs or "avc3" in codecs:
            return "h264"
        if "hvc1" in codecs or "hev1" in codecs:
            return "h265"
        if "av01" in codecs:
            return "av1"
        if "vp09" in codecs or "vp9" in codecs:
            return "vp9"
        if "dvh1" in codecs or "dvhe" in codecs:
            return "dolby-vision"
        # Fallback: return the first codec token or "unknown".
        first = codecs_str.split(",")[0].strip()
        return first if first else "unknown"

    @staticmethod
    def _channel_label(count: int) -> str:
        """Convert a raw channel count to a display label."""
        mapping: dict[int, str] = {
            1: "1.0",
            2: "2.0",
            6: "5.1",
            8: "7.1",
        }
        return mapping.get(count, f"{count}ch")
