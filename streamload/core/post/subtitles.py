"""Subtitle format conversion for Streamload.

Converts between WebVTT, SRT, and ASS subtitle formats.  Used by the
post-processing pipeline when the user's preferred format differs from
what the streaming service provides.

No output is printed to the console -- diagnostics go to the log file.

Usage::

    converter = SubtitleConverter()
    output = converter.convert(Path("subs.vtt"), "srt")
"""

from __future__ import annotations

import re
from pathlib import Path

from streamload.utils.logger import get_logger

log = get_logger(__name__)

# Regex that matches an SRT timestamp line: "HH:MM:SS,mmm --> HH:MM:SS,mmm"
_SRT_TIMESTAMP_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}),(\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}),(\d{3})"
)

# Regex that matches a VTT timestamp line: "HH:MM:SS.mmm --> HH:MM:SS.mmm"
# Also handles short-form "MM:SS.mmm" timestamps.
_VTT_TIMESTAMP_RE = re.compile(
    r"(\d{1,2}:)?(\d{2}:\d{2})\.(\d{3})\s*-->\s*(\d{1,2}:)?(\d{2}:\d{2})\.(\d{3})"
)


class SubtitleConverter:
    """Convert between subtitle formats (VTT, SRT, ASS).

    Supported conversions:

    - VTT -> SRT
    - SRT -> VTT
    - VTT -> ASS (basic)
    - SRT -> ASS (basic)

    Conversion preserves timing and text content but may strip
    format-specific features (e.g. VTT cue settings, ASS overrides).
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def convert(
        self,
        input_path: Path,
        output_format: str,
        output_path: Path | None = None,
    ) -> Path:
        """Convert a subtitle file to the target format.

        Parameters
        ----------
        input_path:
            Path to the source subtitle file.
        output_format:
            Target format: ``"srt"``, ``"vtt"``, or ``"ass"``.
        output_path:
            Optional output file path.  If ``None``, the input path's
            extension is replaced with *output_format*.

        Returns
        -------
        Path
            Path to the converted subtitle file.

        Raises
        ------
        ValueError
            If *output_format* is not supported.
        FileNotFoundError
            If *input_path* does not exist.
        """
        output_format = output_format.lower().strip(".")
        if output_format not in ("srt", "vtt", "ass"):
            raise ValueError(
                f"Unsupported subtitle format: {output_format!r}. "
                f"Supported: srt, vtt, ass"
            )

        if not input_path.exists():
            raise FileNotFoundError(f"Subtitle file not found: {input_path}")

        content = input_path.read_text(encoding="utf-8", errors="replace")
        source_format = self.detect_format(content)

        if output_path is None:
            output_path = input_path.with_suffix(f".{output_format}")

        log.info(
            "Converting subtitles: %s (%s) -> %s (%s)",
            input_path.name, source_format, output_path.name, output_format,
        )

        # No conversion needed if formats match.
        if source_format == output_format:
            if output_path != input_path:
                output_path.write_text(content, encoding="utf-8")
            return output_path

        # Dispatch to the appropriate converter.
        converted = self._dispatch_conversion(content, source_format, output_format)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(converted, encoding="utf-8")

        log.info("Subtitle conversion complete: %s", output_path.name)
        return output_path

    def detect_format(self, content: str) -> str:
        """Detect subtitle format from content.

        Examines the first few lines for format-specific signatures.

        Parameters
        ----------
        content:
            Raw subtitle file content.

        Returns
        -------
        str
            Detected format: ``"vtt"``, ``"srt"``, or ``"ass"``.
        """
        stripped = content.strip()

        # WebVTT always starts with "WEBVTT".
        if stripped.startswith("WEBVTT"):
            return "vtt"

        # ASS/SSA uses [Script Info] section header.
        if stripped.startswith("[Script Info]") or "\n[Script Info]" in stripped[:500]:
            return "ass"

        # SRT: numbered cues followed by timestamp lines.
        # Check if there are SRT-style timestamps.
        if _SRT_TIMESTAMP_RE.search(stripped[:1000]):
            return "srt"

        # VTT-style timestamps without the header (some broken files).
        if _VTT_TIMESTAMP_RE.search(stripped[:1000]):
            return "vtt"

        # Default to SRT as the most common format.
        log.debug("Could not detect subtitle format -- defaulting to SRT")
        return "srt"

    # ------------------------------------------------------------------
    # VTT <-> SRT conversion
    # ------------------------------------------------------------------

    def vtt_to_srt(self, content: str) -> str:
        """Convert WebVTT to SRT format.

        Steps:

        1. Remove the ``WEBVTT`` header and any metadata lines.
        2. Remove cue identifiers and style blocks.
        3. Convert timestamps: dot (``.``) to comma (``,``).
        4. Add sequential cue numbering.
        5. Strip VTT-specific tags (``<c>``, ``<v>``, etc.).

        Parameters
        ----------
        content:
            Raw WebVTT subtitle content.

        Returns
        -------
        str
            SRT-formatted subtitle content.
        """
        lines = content.splitlines()
        cues: list[_SubtitleCue] = []
        current_cue: _SubtitleCue | None = None
        in_header = True
        in_style_block = False

        for line in lines:
            stripped = line.strip()

            # Skip WEBVTT header and metadata.
            if in_header:
                if stripped.startswith("WEBVTT"):
                    continue
                if stripped.startswith("NOTE"):
                    continue
                if stripped.startswith("Kind:") or stripped.startswith("Language:"):
                    continue
                if stripped == "":
                    in_header = False
                    continue
                # Other header lines (X-TIMESTAMP-MAP, etc.).
                if ":" in stripped and "-->" not in stripped:
                    continue
                in_header = False

            # Skip STYLE blocks.
            if stripped.upper() == "STYLE":
                in_style_block = True
                continue
            if in_style_block:
                if stripped == "":
                    in_style_block = False
                continue

            # Detect timestamp line.
            ts_match = _VTT_TIMESTAMP_RE.search(stripped)
            if ts_match:
                # Save previous cue.
                if current_cue and current_cue.text.strip():
                    cues.append(current_cue)

                # Convert VTT timestamp to SRT format.
                srt_timestamp = self._vtt_ts_to_srt_ts(stripped)
                current_cue = _SubtitleCue(timestamp=srt_timestamp, text="")
                continue

            # Text content.
            if current_cue is not None:
                if stripped == "":
                    # End of cue.
                    if current_cue.text.strip():
                        cues.append(current_cue)
                    current_cue = None
                else:
                    # Skip numeric-only lines that are VTT cue identifiers.
                    if stripped.isdigit() and not current_cue.text:
                        continue
                    text_line = self._strip_vtt_tags(stripped)
                    if current_cue.text:
                        current_cue.text += "\n" + text_line
                    else:
                        current_cue.text = text_line
            else:
                # Line outside a cue -- might be a cue identifier (skip).
                pass

        # Don't forget the last cue.
        if current_cue and current_cue.text.strip():
            cues.append(current_cue)

        # Build SRT output.
        parts: list[str] = []
        for idx, cue in enumerate(cues, start=1):
            parts.append(f"{idx}")
            parts.append(cue.timestamp)
            parts.append(cue.text)
            parts.append("")  # Blank line between cues.

        return "\n".join(parts).strip() + "\n"

    def srt_to_vtt(self, content: str) -> str:
        """Convert SRT to WebVTT format.

        Steps:

        1. Add ``WEBVTT`` header.
        2. Convert timestamps: comma (``,``) to dot (``.``).
        3. Remove cue numbering.

        Parameters
        ----------
        content:
            Raw SRT subtitle content.

        Returns
        -------
        str
            WebVTT-formatted subtitle content.
        """
        lines = content.splitlines()
        output_lines: list[str] = ["WEBVTT", ""]
        in_cue = False

        for line in lines:
            stripped = line.strip()

            # Skip cue numbers (digit-only lines before timestamps).
            if stripped.isdigit() and not in_cue:
                continue

            # Convert SRT timestamps to VTT format.
            ts_match = _SRT_TIMESTAMP_RE.search(stripped)
            if ts_match:
                vtt_ts = stripped.replace(",", ".")
                output_lines.append(vtt_ts)
                in_cue = True
                continue

            if stripped == "":
                in_cue = False
                output_lines.append("")
                continue

            # Regular text line.
            output_lines.append(stripped)

        result = "\n".join(output_lines).strip()
        return result + "\n"

    # ------------------------------------------------------------------
    # ASS conversion
    # ------------------------------------------------------------------

    def srt_to_ass(self, content: str) -> str:
        """Convert SRT to ASS (Advanced SubStation Alpha) format.

        Produces a basic ASS file with default styling.

        Parameters
        ----------
        content:
            Raw SRT subtitle content.

        Returns
        -------
        str
            ASS-formatted subtitle content.
        """
        lines = content.splitlines()
        events: list[str] = []
        current_start: str = ""
        current_end: str = ""
        current_text_lines: list[str] = []

        for line in lines:
            stripped = line.strip()

            # Skip cue numbers.
            if stripped.isdigit() and not current_start:
                continue

            # Parse timestamp line.
            ts_match = _SRT_TIMESTAMP_RE.search(stripped)
            if ts_match:
                # Flush previous event.
                if current_start and current_text_lines:
                    text = "\\N".join(current_text_lines)
                    text = self._strip_html_tags(text)
                    events.append(
                        f"Dialogue: 0,{current_start},{current_end},Default,,0,0,0,,{text}"
                    )
                    current_text_lines = []

                # Parse SRT timestamps into ASS format.
                # SRT:  HH:MM:SS,mmm -> ASS:  H:MM:SS.cc
                current_start = self._srt_ts_to_ass_ts(
                    f"{ts_match.group(1)},{ts_match.group(2)}"
                )
                current_end = self._srt_ts_to_ass_ts(
                    f"{ts_match.group(3)},{ts_match.group(4)}"
                )
                continue

            if stripped == "":
                if current_start and current_text_lines:
                    text = "\\N".join(current_text_lines)
                    text = self._strip_html_tags(text)
                    events.append(
                        f"Dialogue: 0,{current_start},{current_end},Default,,0,0,0,,{text}"
                    )
                    current_text_lines = []
                    current_start = ""
                    current_end = ""
                continue

            if current_start:
                current_text_lines.append(stripped)

        # Flush final event.
        if current_start and current_text_lines:
            text = "\\N".join(current_text_lines)
            text = self._strip_html_tags(text)
            events.append(
                f"Dialogue: 0,{current_start},{current_end},Default,,0,0,0,,{text}"
            )

        return self._build_ass_document(events)

    def vtt_to_ass(self, content: str) -> str:
        """Convert WebVTT to ASS format.

        Converts VTT -> SRT first, then SRT -> ASS.

        Parameters
        ----------
        content:
            Raw WebVTT subtitle content.

        Returns
        -------
        str
            ASS-formatted subtitle content.
        """
        srt_content = self.vtt_to_srt(content)
        return self.srt_to_ass(srt_content)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dispatch_conversion(
        self,
        content: str,
        source: str,
        target: str,
    ) -> str:
        """Route to the appropriate conversion method.

        Parameters
        ----------
        content:
            Raw subtitle content.
        source:
            Detected source format.
        target:
            Desired target format.

        Returns
        -------
        str
            Converted subtitle content.

        Raises
        ------
        ValueError
            If the conversion is not supported.
        """
        dispatch = {
            ("vtt", "srt"): self.vtt_to_srt,
            ("srt", "vtt"): self.srt_to_vtt,
            ("vtt", "ass"): self.vtt_to_ass,
            ("srt", "ass"): self.srt_to_ass,
        }

        converter = dispatch.get((source, target))
        if converter is None:
            raise ValueError(
                f"Unsupported conversion: {source} -> {target}. "
                f"Supported: {', '.join(f'{s}->{t}' for s, t in dispatch)}"
            )

        return converter(content)

    @staticmethod
    def _vtt_ts_to_srt_ts(vtt_line: str) -> str:
        """Convert a VTT timestamp line to SRT format.

        Replaces dots with commas in the timestamps and ensures
        ``HH:MM:SS,mmm`` format.  Also strips VTT cue settings that
        follow the timestamp arrow.

        Parameters
        ----------
        vtt_line:
            A line containing a VTT timestamp (e.g.
            ``"00:01:23.456 --> 00:01:25.789 position:10%"``).

        Returns
        -------
        str
            SRT-formatted timestamp line.
        """
        # Extract just the timestamp portion.
        arrow_idx = vtt_line.index("-->")
        start_raw = vtt_line[:arrow_idx].strip()
        rest = vtt_line[arrow_idx + 3:].strip()
        # End timestamp might have cue settings after it.
        end_parts = rest.split()
        end_raw = end_parts[0] if end_parts else rest

        start = _normalise_vtt_timestamp(start_raw)
        end = _normalise_vtt_timestamp(end_raw)

        return f"{start} --> {end}"

    @staticmethod
    def _srt_ts_to_ass_ts(srt_ts: str) -> str:
        """Convert an SRT timestamp to ASS format.

        SRT:  ``HH:MM:SS,mmm``
        ASS:  ``H:MM:SS.cc`` (centiseconds, single-digit hour).

        Parameters
        ----------
        srt_ts:
            SRT-format timestamp (e.g. ``"01:23:45,678"``).

        Returns
        -------
        str
            ASS-format timestamp (e.g. ``"1:23:45.67"``).
        """
        # Split "HH:MM:SS,mmm"
        time_part, ms_part = srt_ts.split(",")
        parts = time_part.split(":")
        hours = int(parts[0])
        minutes = parts[1]
        seconds = parts[2]
        centiseconds = ms_part[:2]  # Truncate to centiseconds.

        return f"{hours}:{minutes}:{seconds}.{centiseconds}"

    @staticmethod
    def _strip_vtt_tags(text: str) -> str:
        """Remove VTT-specific markup tags from text.

        Strips tags like ``<c>``, ``</c>``, ``<v Speaker>``,
        ``<b>``, ``<i>``, ``<u>``, ``<ruby>``, ``<rt>``, etc.
        Preserves basic HTML-like ``<b>``, ``<i>``, ``<u>`` for SRT
        compatibility.
        """
        # Remove voice tags: <v Speaker Name>
        text = re.sub(r"<v\s+[^>]*>", "", text)
        # Remove class tags: <c.classname>
        text = re.sub(r"<c\.[^>]*>", "", text)
        # Remove timestamp tags: <00:01:23.456>
        text = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", text)
        # Remove closing tags for VTT-specific elements.
        text = re.sub(r"</[cv]>", "", text)
        # Remove ruby/rt tags.
        text = re.sub(r"</?(?:ruby|rt)>", "", text)
        return text.strip()

    @staticmethod
    def _strip_html_tags(text: str) -> str:
        """Remove all HTML/XML-like tags from text."""
        return re.sub(r"<[^>]+>", "", text)

    @staticmethod
    def _build_ass_document(events: list[str]) -> str:
        """Build a complete ASS document with default styling.

        Parameters
        ----------
        events:
            List of ``Dialogue:`` lines.

        Returns
        -------
        str
            Complete ASS file content.
        """
        header = (
            "[Script Info]\n"
            "Title: Streamload Subtitles\n"
            "ScriptType: v4.00+\n"
            "WrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n"
            "YCbCr Matrix: None\n"
            "PlayResX: 1920\n"
            "PlayResY: 1080\n"
            "\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Arial,56,&H00FFFFFF,&H000000FF,&H00000000,"
            "&H80000000,-1,0,0,0,100,100,0,0,1,2.5,1,2,30,30,45,1\n"
            "\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
            "Effect, Text\n"
        )

        return header + "\n".join(events) + "\n"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _SubtitleCue:
    """Temporary holder for a subtitle cue during conversion."""

    __slots__ = ("timestamp", "text")

    def __init__(self, timestamp: str, text: str) -> None:
        self.timestamp = timestamp
        self.text = text


def _normalise_vtt_timestamp(ts: str) -> str:
    """Normalise a VTT timestamp to ``HH:MM:SS,mmm`` (SRT format).

    Handles short-form ``MM:SS.mmm`` by prepending ``00:``.
    Replaces the dot separator with a comma.

    Parameters
    ----------
    ts:
        A VTT-style timestamp (e.g. ``"01:23.456"`` or
        ``"01:23:45.678"``).

    Returns
    -------
    str
        Normalised SRT-format timestamp.
    """
    # Replace dot with comma for SRT.
    ts = ts.replace(".", ",")
    # Count colons to determine if hours are present.
    if ts.count(":") == 1:
        # Short form: MM:SS,mmm -> 00:MM:SS,mmm
        ts = "00:" + ts
    return ts
