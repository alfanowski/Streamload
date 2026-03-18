"""DASH MPD manifest parser for Streamload.

Parses MPEG-DASH Media Presentation Description XML documents,
extracting video/audio/subtitle tracks, DRM metadata (Widevine and
PlayReady PSSH), and segment URLs.  Only uses the standard library
:mod:`xml.etree.ElementTree` -- no third-party dependencies.

The parser is namespace-aware and tolerant of missing or unexpected
elements so that minor CDN variations never cause hard failures.
"""

from __future__ import annotations

import base64
import logging
import math
import re
import xml.etree.ElementTree as ET
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
# XML namespace helpers
# ---------------------------------------------------------------------------

# The two namespaces we care about.  When fetching elements the full
# Clark notation ``{uri}local`` is required by ElementTree.
_NS_MPD = "urn:mpeg:dash:schema:mpd:2011"
_NS_CENC = "urn:mpeg:cenc:2013"

# Namespace map for convenience (ElementTree does *not* accept prefixes
# in ``find`` / ``findall`` -- only the ``{uri}tag`` form -- so we build
# the fully-qualified tag names ourselves).
_NS = {
    "mpd": _NS_MPD,
    "cenc": _NS_CENC,
}


def _tag(ns_prefix: str, local: str) -> str:
    """Return the Clark-notation tag ``{namespace}local``."""
    return f"{{{_NS[ns_prefix]}}}{local}"


# ---------------------------------------------------------------------------
# Data models local to DASH parsing
# ---------------------------------------------------------------------------


@dataclass
class DASHSegment:
    """A single media segment in a DASH representation."""

    url: str
    init_url: str | None = None
    duration: float = 0.0
    number: int = 0


@dataclass
class DASHRepresentation:
    """Parsed segment list for one DASH representation."""

    segments: list[DASHSegment] = field(default_factory=list)
    init_url: str | None = None
    total_duration: float = 0.0


# ---------------------------------------------------------------------------
# Duration parsing (ISO 8601)
# ---------------------------------------------------------------------------

_ISO8601_RE = re.compile(
    r"P(?:(?P<years>\d+)Y)?"
    r"(?:(?P<months>\d+)M)?"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>[\d.]+)S)?"
    r")?",
)


def _parse_duration(raw: str | None) -> float:
    """Parse an ISO 8601 duration string into seconds.

    Returns ``0.0`` for ``None`` or unparseable values.

    Examples::

        "PT1H30M15.5S" -> 5415.5
        "PT60S"        -> 60.0
        "P1DT12H"     -> 129600.0
    """
    if not raw:
        return 0.0
    m = _ISO8601_RE.match(raw.strip())
    if not m:
        return 0.0
    years = int(m.group("years") or 0)
    months = int(m.group("months") or 0)
    days = int(m.group("days") or 0)
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    seconds = float(m.group("seconds") or 0)
    # Approximate years/months (rarely used but technically valid).
    return (
        years * 365.25 * 86400
        + months * 30.4375 * 86400
        + days * 86400
        + hours * 3600
        + minutes * 60
        + seconds
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class MPDParser:
    """Parse DASH MPD manifests into structured data.

    Usage::

        parser = MPDParser()

        # Full manifest -> StreamBundle with tracks + DRM info
        bundle = parser.parse(mpd_text, mpd_url)

        # Segment list for one representation
        rep = parser.get_segments(mpd_text, mpd_url, representation_id)
    """

    # Well-known DRM scheme URIs.
    WIDEVINE_SCHEME: str = "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"
    PLAYREADY_SCHEME: str = "urn:uuid:9a04f079-9840-4286-ab92-e65be0885f95"

    # -- Public API ---------------------------------------------------------

    def parse(self, content: str, base_url: str) -> StreamBundle:
        """Parse an MPD manifest and extract all tracks and DRM info.

        Parameters
        ----------
        content:
            Raw XML text of the MPD document.
        base_url:
            URL the manifest was fetched from, used to resolve relative URIs.

        Returns
        -------
        StreamBundle:
            Populated ``video``, ``audio``, ``subtitles``, plus ``drm_type``
            and ``pssh`` when DRM content protection is present.
        """
        root = self._parse_xml(content)

        video_tracks: list[VideoTrack] = []
        audio_tracks: list[AudioTrack] = []
        subtitle_tracks: list[SubtitleTrack] = []
        drm_type: str | None = None
        pssh: str | None = None

        # Resolve document-level BaseURL.
        base_url = self._resolve_base_url(root, base_url)

        for period in root.findall(_tag("mpd", "Period")):
            period_base = self._resolve_base_url(period, base_url)
            period_duration = _parse_duration(
                period.get("duration") or root.get("mediaPresentationDuration"),
            )

            for adaptation in period.findall(_tag("mpd", "AdaptationSet")):
                adapt_base = self._resolve_base_url(adaptation, period_base)
                content_type = self._detect_content_type(adaptation)

                # Extract DRM from the AdaptationSet level.
                if drm_type is None:
                    _pssh, _drm = self._extract_pssh(adaptation)
                    if _drm is not None:
                        pssh = _pssh
                        drm_type = _drm

                for rep in adaptation.findall(_tag("mpd", "Representation")):
                    rep_base = self._resolve_base_url(rep, adapt_base)
                    rep_id = rep.get("id", "")

                    # DRM can also sit at Representation level.
                    if drm_type is None:
                        _pssh, _drm = self._extract_pssh(rep)
                        if _drm is not None:
                            pssh = _pssh
                            drm_type = _drm

                    if content_type == "video":
                        video_tracks.append(
                            self._build_video_track(rep, adaptation, rep_base),
                        )
                    elif content_type == "audio":
                        audio_tracks.append(
                            self._build_audio_track(rep, adaptation, rep_base),
                        )
                    elif content_type == "subtitle":
                        subtitle_tracks.append(
                            self._build_subtitle_track(rep, adaptation, rep_base),
                        )

        return StreamBundle(
            video=video_tracks,
            audio=audio_tracks,
            subtitles=subtitle_tracks,
            drm_type=drm_type,
            pssh=pssh,
            manifest_url=base_url,
        )

    def get_segments(
        self, content: str, base_url: str, representation_id: str,
    ) -> DASHRepresentation:
        """Get segment URLs for a specific representation.

        Parameters
        ----------
        content:
            Raw MPD XML.
        base_url:
            URL the manifest was fetched from.
        representation_id:
            The ``id`` attribute of the target ``<Representation>``.

        Returns
        -------
        DASHRepresentation:
            Populated segment list with resolved URLs.
        """
        root = self._parse_xml(content)
        base_url = self._resolve_base_url(root, base_url)

        for period in root.findall(_tag("mpd", "Period")):
            period_base = self._resolve_base_url(period, base_url)
            period_duration = _parse_duration(
                period.get("duration") or root.get("mediaPresentationDuration"),
            )

            for adaptation in period.findall(_tag("mpd", "AdaptationSet")):
                adapt_base = self._resolve_base_url(adaptation, period_base)

                # Grab the SegmentTemplate at AdaptationSet level as a fallback.
                adapt_seg_template = adaptation.find(_tag("mpd", "SegmentTemplate"))

                for rep in adaptation.findall(_tag("mpd", "Representation")):
                    if rep.get("id") != representation_id:
                        continue

                    rep_base = self._resolve_base_url(rep, adapt_base)

                    # SegmentTemplate at Representation level overrides AdaptationSet.
                    seg_template = rep.find(_tag("mpd", "SegmentTemplate"))
                    if seg_template is None:
                        seg_template = adapt_seg_template

                    if seg_template is not None:
                        segments = self._parse_segment_template(
                            seg_template, rep, period_duration, rep_base,
                        )
                        init_url = self._template_init_url(
                            seg_template, rep, rep_base,
                        )
                        total = sum(s.duration for s in segments)
                        return DASHRepresentation(
                            segments=segments,
                            init_url=init_url,
                            total_duration=total,
                        )

                    # SegmentList fallback.
                    seg_list = rep.find(_tag("mpd", "SegmentList"))
                    if seg_list is None:
                        seg_list = adaptation.find(_tag("mpd", "SegmentList"))
                    if seg_list is not None:
                        segments = self._parse_segment_list(
                            seg_list, period_duration, rep_base,
                        )
                        init_el = seg_list.find(_tag("mpd", "Initialization"))
                        init_url = (
                            self._resolve_url(init_el.get("sourceURL", ""), rep_base)
                            if init_el is not None and init_el.get("sourceURL")
                            else None
                        )
                        total = sum(s.duration for s in segments)
                        return DASHRepresentation(
                            segments=segments,
                            init_url=init_url,
                            total_duration=total,
                        )

                    # SegmentBase (single-segment, usually with byte ranges).
                    seg_base = rep.find(_tag("mpd", "SegmentBase"))
                    if seg_base is None:
                        seg_base = adaptation.find(_tag("mpd", "SegmentBase"))
                    if seg_base is not None:
                        init_el = seg_base.find(_tag("mpd", "Initialization"))
                        init_url = (
                            self._resolve_url(
                                init_el.get("sourceURL", rep_base), rep_base,
                            )
                            if init_el is not None
                            else None
                        )
                        return DASHRepresentation(
                            segments=[DASHSegment(url=rep_base, duration=period_duration)],
                            init_url=init_url,
                            total_duration=period_duration,
                        )

                    # Bare BaseURL (single file).
                    return DASHRepresentation(
                        segments=[DASHSegment(url=rep_base, duration=period_duration)],
                        total_duration=period_duration,
                    )

        # Representation not found -- return empty.
        log.warning("Representation %r not found in MPD", representation_id)
        return DASHRepresentation()

    # -- DRM extraction -----------------------------------------------------

    def _extract_pssh(
        self, element: ET.Element,
    ) -> tuple[str | None, str | None]:
        """Extract PSSH box and identify DRM type from ContentProtection elements.

        Searches *element* (an AdaptationSet or Representation) for
        ``<ContentProtection>`` children, looking for Widevine or
        PlayReady ``schemeIdUri`` values and an embedded ``<cenc:pssh>``
        element.

        Returns
        -------
        tuple[str | None, str | None]:
            ``(pssh_b64, drm_type)`` where *drm_type* is ``"widevine"``
            or ``"playready"`` (or ``None`` when no recognised DRM is
            found).
        """
        pssh_b64: str | None = None
        drm_type: str | None = None

        for cp in element.findall(_tag("mpd", "ContentProtection")):
            scheme = (cp.get("schemeIdUri") or "").lower()

            # Identify the DRM system.
            detected: str | None = None
            if scheme == self.WIDEVINE_SCHEME:
                detected = "widevine"
            elif scheme == self.PLAYREADY_SCHEME:
                detected = "playready"

            if detected is not None:
                # Prefer Widevine when both are present.
                if drm_type is None or detected == "widevine":
                    drm_type = detected

                # Look for <cenc:pssh> child.
                pssh_el = cp.find(_tag("cenc", "pssh"))
                if pssh_el is not None and pssh_el.text:
                    candidate = pssh_el.text.strip()
                    # Validate that this is plausible base64.
                    try:
                        base64.b64decode(candidate, validate=True)
                        # Prefer Widevine PSSH when both exist.
                        if pssh_b64 is None or detected == "widevine":
                            pssh_b64 = candidate
                    except Exception:
                        log.debug("Ignoring invalid base64 in PSSH element")

        return pssh_b64, drm_type

    # -- Track builders -----------------------------------------------------

    def _build_video_track(
        self,
        rep: ET.Element,
        adaptation: ET.Element,
        base_url: str,
    ) -> VideoTrack:
        """Construct a :class:`VideoTrack` from a DASH Representation."""
        rep_id = rep.get("id", "")
        width = self._int_attr(rep, "width") or self._int_attr(adaptation, "width") or 0
        height = self._int_attr(rep, "height") or self._int_attr(adaptation, "height") or 0
        bandwidth = self._int_attr(rep, "bandwidth")
        codecs = rep.get("codecs") or adaptation.get("codecs") or ""
        codec = self._normalise_video_codec(codecs)

        fps = self._parse_frame_rate(
            rep.get("frameRate") or adaptation.get("frameRate"),
        )

        # HDR detection: check for HDR-related supplemental properties or
        # codecs that signal high dynamic range (e.g. hev1.2.* profiles).
        hdr = self._detect_hdr(rep, adaptation, codecs)

        return VideoTrack(
            id=rep_id,
            resolution=f"{width}x{height}",
            codec=codec,
            bitrate=bandwidth,
            fps=fps,
            hdr=hdr,
        )

    def _build_audio_track(
        self,
        rep: ET.Element,
        adaptation: ET.Element,
        base_url: str,
    ) -> AudioTrack:
        """Construct an :class:`AudioTrack` from a DASH Representation."""
        rep_id = rep.get("id", "")
        lang = adaptation.get("lang") or rep.get("lang") or "und"
        codecs = rep.get("codecs") or adaptation.get("codecs") or ""
        codec = self._normalise_audio_codec(codecs)
        bandwidth = self._int_attr(rep, "bandwidth")

        # Channel count from AudioChannelConfiguration.
        channels = self._extract_channel_config(rep) or self._extract_channel_config(adaptation)
        channel_label = self._channel_label(channels or 2)

        # Human name from label attribute or Role element.
        name = adaptation.get("label") or self._extract_role(adaptation)

        return AudioTrack(
            id=rep_id,
            language=lang,
            codec=codec,
            channels=channel_label,
            bitrate=bandwidth,
            name=name,
        )

    def _build_subtitle_track(
        self,
        rep: ET.Element,
        adaptation: ET.Element,
        base_url: str,
    ) -> SubtitleTrack:
        """Construct a :class:`SubtitleTrack` from a DASH Representation."""
        rep_id = rep.get("id", "")
        lang = adaptation.get("lang") or rep.get("lang") or "und"

        mime = rep.get("mimeType") or adaptation.get("mimeType") or ""
        fmt = self._subtitle_format(mime, rep.get("codecs") or "")

        # Forced flag from Role element with value "forced".
        forced = self._is_forced(adaptation)

        name = adaptation.get("label")

        return SubtitleTrack(
            id=rep_id,
            language=lang,
            format=fmt,
            forced=forced,
            name=name,
        )

    # -- Content-type detection ---------------------------------------------

    @staticmethod
    def _detect_content_type(adaptation: ET.Element) -> str:
        """Determine whether an AdaptationSet carries video, audio, or subtitles.

        Checks (in order): ``contentType`` attribute, ``mimeType``
        attribute, then falls back to inspecting child Representations.
        """
        ct = (adaptation.get("contentType") or "").lower()
        if ct in ("video", "audio", "text"):
            return "subtitle" if ct == "text" else ct

        mime = (adaptation.get("mimeType") or "").lower()
        if "video" in mime:
            return "video"
        if "audio" in mime:
            return "audio"
        if "text" in mime or "subtitle" in mime or "application/ttml" in mime:
            return "subtitle"

        # Last resort: check first Representation's mimeType.
        for rep in adaptation.findall(_tag("mpd", "Representation")):
            rep_mime = (rep.get("mimeType") or "").lower()
            if "video" in rep_mime:
                return "video"
            if "audio" in rep_mime:
                return "audio"
            if "text" in rep_mime or "subtitle" in rep_mime:
                return "subtitle"
            # Width/height imply video.
            if rep.get("width") or rep.get("height"):
                return "video"

        return "video"  # conservative default

    # -- Segment parsing ----------------------------------------------------

    def _parse_segment_template(
        self,
        template: ET.Element,
        representation: ET.Element,
        period_duration: float,
        base_url: str,
    ) -> list[DASHSegment]:
        """Generate segment URLs from a ``<SegmentTemplate>``.

        Handles both ``$Number$``-based and ``$Time$``-based templates,
        including ``<SegmentTimeline>`` children.
        """
        media_pattern = template.get("media", "")
        timescale = int(template.get("timescale", "1"))
        start_number = int(template.get("startNumber", "1"))
        rep_id = representation.get("id", "")
        bandwidth = representation.get("bandwidth", "0")

        segments: list[DASHSegment] = []

        # Check for SegmentTimeline.
        timeline = template.find(_tag("mpd", "SegmentTimeline"))

        if timeline is not None:
            # Explicit timeline: each <S> element gives a segment time,
            # duration, and optional repeat count.
            seg_num = start_number
            current_time = 0

            for s_el in timeline.findall(_tag("mpd", "S")):
                t = s_el.get("t")
                if t is not None:
                    current_time = int(t)
                d = int(s_el.get("d", "0"))
                r = int(s_el.get("r", "0"))

                # r == -1 means "repeat until end of period".
                if r < 0 and period_duration > 0 and d > 0:
                    remaining = period_duration * timescale - current_time
                    r = max(0, math.ceil(remaining / d) - 1)

                for _ in range(r + 1):
                    url = self._substitute_template(
                        media_pattern, rep_id, bandwidth, seg_num, current_time,
                    )
                    seg_duration = d / timescale if timescale else 0.0
                    segments.append(DASHSegment(
                        url=self._resolve_url(url, base_url),
                        duration=seg_duration,
                        number=seg_num,
                    ))
                    current_time += d
                    seg_num += 1
        else:
            # No timeline -- use flat ``duration`` attribute.
            seg_duration_ticks = int(template.get("duration", "0"))
            if seg_duration_ticks <= 0 or timescale <= 0:
                return segments

            seg_duration = seg_duration_ticks / timescale
            if period_duration <= 0:
                return segments

            segment_count = math.ceil(period_duration / seg_duration)
            current_time = 0

            for i in range(segment_count):
                seg_num = start_number + i
                url = self._substitute_template(
                    media_pattern, rep_id, bandwidth, seg_num, current_time,
                )
                segments.append(DASHSegment(
                    url=self._resolve_url(url, base_url),
                    duration=seg_duration,
                    number=seg_num,
                ))
                current_time += seg_duration_ticks

        return segments

    def _parse_segment_list(
        self,
        seg_list: ET.Element,
        period_duration: float,
        base_url: str,
    ) -> list[DASHSegment]:
        """Parse a ``<SegmentList>`` element into segment objects."""
        timescale = int(seg_list.get("timescale", "1"))
        duration_ticks = int(seg_list.get("duration", "0"))
        seg_duration = duration_ticks / timescale if timescale and duration_ticks else 0.0

        segments: list[DASHSegment] = []
        for idx, seg_url_el in enumerate(
            seg_list.findall(_tag("mpd", "SegmentURL"))
        ):
            media = seg_url_el.get("media", "")
            if not media:
                continue
            segments.append(DASHSegment(
                url=self._resolve_url(media, base_url),
                duration=seg_duration if seg_duration else period_duration,
                number=idx,
            ))

        return segments

    def _template_init_url(
        self,
        template: ET.Element,
        representation: ET.Element,
        base_url: str,
    ) -> str | None:
        """Resolve the initialisation URL from a SegmentTemplate."""
        init_pattern = template.get("initialization") or template.get("initialisation")
        if not init_pattern:
            # Look for <Initialization> child element.
            init_el = template.find(_tag("mpd", "Initialization"))
            if init_el is not None:
                init_pattern = init_el.get("sourceURL")
        if not init_pattern:
            return None

        rep_id = representation.get("id", "")
        bandwidth = representation.get("bandwidth", "0")
        url = self._substitute_template(init_pattern, rep_id, bandwidth, 0, 0)
        return self._resolve_url(url, base_url)

    @staticmethod
    def _substitute_template(
        pattern: str,
        rep_id: str,
        bandwidth: str,
        number: int,
        time: int,
    ) -> str:
        """Apply DASH template variable substitution.

        Handles ``$RepresentationID$``, ``$Bandwidth$``, ``$Number$``,
        ``$Time$``, and their ``%0Nd``-padded variants
        (e.g. ``$Number%05d$``).
        """
        result = pattern
        result = result.replace("$RepresentationID$", rep_id)
        result = result.replace("$Bandwidth$", bandwidth)

        # $Number$ and $Number%0Nd$
        result = _template_substitute_var(result, "Number", number)
        # $Time$ and $Time%0Nd$
        result = _template_substitute_var(result, "Time", time)

        return result

    # -- URL resolution -----------------------------------------------------

    def _resolve_url(self, url: str, base_url: str) -> str:
        """Resolve a relative URL against *base_url*."""
        if url.startswith(("http://", "https://", "data:")):
            return url
        return urljoin(base_url, url)

    def _resolve_base_url(self, element: ET.Element, parent_base: str) -> str:
        """Find a ``<BaseURL>`` child and resolve it against *parent_base*."""
        base_el = element.find(_tag("mpd", "BaseURL"))
        if base_el is not None and base_el.text:
            return self._resolve_url(base_el.text.strip(), parent_base)
        return parent_base

    # -- XML ----------------------------------------------------------------

    @staticmethod
    def _parse_xml(content: str) -> ET.Element:
        """Parse an XML string, stripping the UTF-8 BOM if present."""
        content = content.lstrip("\ufeff")
        return ET.fromstring(content)

    # -- Attribute helpers --------------------------------------------------

    @staticmethod
    def _int_attr(element: ET.Element, name: str) -> int | None:
        """Read an integer attribute, returning ``None`` on failure."""
        raw = element.get(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    @staticmethod
    def _parse_frame_rate(raw: str | None) -> float | None:
        """Parse a frame-rate string like ``"30"`` or ``"30000/1001"``."""
        if not raw:
            return None
        if "/" in raw:
            parts = raw.split("/")
            try:
                return round(float(parts[0]) / float(parts[1]), 3)
            except (ValueError, ZeroDivisionError):
                return None
        try:
            return float(raw)
        except ValueError:
            return None

    @staticmethod
    def _normalise_video_codec(codecs: str) -> str:
        """Map a DASH codecs string to a friendly name."""
        c = codecs.lower()
        if "avc1" in c or "avc3" in c:
            return "h264"
        if "hvc1" in c or "hev1" in c:
            return "h265"
        if "av01" in c:
            return "av1"
        if "vp09" in c or "vp9" in c:
            return "vp9"
        if "dvh1" in c or "dvhe" in c:
            return "dolby-vision"
        first = codecs.split(",")[0].strip()
        return first if first else "unknown"

    @staticmethod
    def _normalise_audio_codec(codecs: str) -> str:
        """Map a DASH audio codecs string to a friendly name."""
        c = codecs.lower()
        if "mp4a.40" in c:
            return "aac"
        if "ec-3" in c or "ec3" in c:
            return "eac3"
        if "ac-3" in c or "ac3" in c:
            return "ac3"
        if "opus" in c:
            return "opus"
        if "dtsc" in c or "dtse" in c or "dtsh" in c or "dtsl" in c:
            return "dts"
        if "flac" in c:
            return "flac"
        if "vorbis" in c:
            return "vorbis"
        first = codecs.split(",")[0].strip()
        return first if first else "aac"

    @staticmethod
    def _subtitle_format(mime: str, codecs: str) -> str:
        """Determine subtitle format from mimeType and codecs."""
        mime_lower = mime.lower()
        codecs_lower = codecs.lower()
        if "ttml" in mime_lower or "stpp" in codecs_lower or "ttml" in codecs_lower:
            return "ttml"
        if "vtt" in mime_lower or "wvtt" in codecs_lower:
            return "vtt"
        if "srt" in mime_lower:
            return "srt"
        return "vtt"

    def _extract_channel_config(self, element: ET.Element) -> int | None:
        """Read AudioChannelConfiguration value from *element*."""
        for tag_name in (
            _tag("mpd", "AudioChannelConfiguration"),
            # Some manifests omit the namespace on this element.
            "AudioChannelConfiguration",
        ):
            el = element.find(tag_name)
            if el is not None:
                raw = el.get("value", "")
                try:
                    return int(raw)
                except ValueError:
                    # Some use hex channel masks -- count bits.
                    try:
                        mask = int(raw, 16)
                        return bin(mask).count("1")
                    except ValueError:
                        pass
        return None

    @staticmethod
    def _extract_role(adaptation: ET.Element) -> str | None:
        """Extract a Role value (e.g. ``"main"``, ``"commentary"``)."""
        role = adaptation.find(_tag("mpd", "Role"))
        if role is not None:
            return role.get("value")
        return None

    @staticmethod
    def _is_forced(adaptation: ET.Element) -> bool:
        """Detect forced subtitles from Role or forced attribute."""
        role = adaptation.find(_tag("mpd", "Role"))
        if role is not None and (role.get("value") or "").lower() == "forced":
            return True
        if adaptation.get("forced", "").lower() in ("true", "1"):
            return True
        return False

    @staticmethod
    def _detect_hdr(
        rep: ET.Element, adaptation: ET.Element, codecs: str,
    ) -> bool:
        """Detect HDR from supplemental properties or codec profiles."""
        # HEVC Main 10 profile (profile 2) signals HDR capability.
        c = codecs.lower()
        if "hev1.2" in c or "hvc1.2" in c:
            return True

        # Check for essential/supplemental properties indicating HDR.
        for parent in (rep, adaptation):
            for prop_tag in (
                _tag("mpd", "SupplementalProperty"),
                _tag("mpd", "EssentialProperty"),
            ):
                for prop in parent.findall(prop_tag):
                    scheme = (prop.get("schemeIdUri") or "").lower()
                    value = (prop.get("value") or "").lower()
                    # CICP transfer characteristics: PQ=16, HLG=18.
                    if "cicp" in scheme and value in ("16", "18"):
                        return True
        return False

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


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _template_substitute_var(pattern: str, name: str, value: int) -> str:
    """Replace ``$Name$`` and ``$Name%0Nd$`` in *pattern* with *value*.

    Handles width-padded formats such as ``$Number%05d$`` by zero-padding
    the value to the requested width.
    """
    # First try the padded form: $Name%0Nd$
    padded_re = re.compile(re.escape(f"${name}") + r"%(\d+)d\$")
    m = padded_re.search(pattern)
    if m:
        width = int(m.group(1))
        replacement = str(value).zfill(width)
        return padded_re.sub(replacement, pattern)

    # Plain form: $Name$
    return pattern.replace(f"${name}$", str(value))
