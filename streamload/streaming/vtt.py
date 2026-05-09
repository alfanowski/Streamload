"""WebVTT detection + SRT→VTT conversion (browsers want VTT)."""
from __future__ import annotations

import re


def is_webvtt(text: str) -> bool:
    return text.strip().startswith("WEBVTT")


_SRT_TIMING_RE = re.compile(r"(\d{2}:\d{2}:\d{2}),(\d{3})")


def srt_to_vtt(srt: str) -> str:
    """Minimal SRT to WebVTT conversion (timing comma → dot, prepend header)."""
    body = _SRT_TIMING_RE.sub(r"\1.\2", srt)
    return "WEBVTT\n\n" + body
