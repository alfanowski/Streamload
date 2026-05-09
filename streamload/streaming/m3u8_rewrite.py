"""HLS master + media playlist URL rewriting.

Rewrites in two passes:

1. ``rewrite_master(text, session_id, base_path)`` — replaces every
   stream-inf, audio, and subtitle URI to point at our backend's
   `/stream/{session_id}/...` proxy paths. Strips upstream tokens
   from URLs returned to the browser.

2. ``rewrite_media(text, session_id, rendition, base_path)`` — replaces
   each segment URI with `/stream/{session_id}/seg/{rendition}/{n}.ts`.

The mapping from rendition label (e.g. "480p") to upstream URL is
maintained server-side in the playback session.
"""
from __future__ import annotations

import re

_STREAM_INF_RE = re.compile(r"^#EXT-X-STREAM-INF:.*?$", re.MULTILINE)
_RESOLUTION_RE = re.compile(r"RESOLUTION=(\d+)x(\d+)")
_RENDITION_PARAM_RE = re.compile(r"rendition=([^&\"\s]+)")
_AUDIO_LANG_RE = re.compile(r'LANGUAGE="([^"]+)".*?URI="[^"]+"', re.DOTALL)
_URI_ATTR_RE = re.compile(r'URI="([^"]+)"')


def _label_for_rendition(url: str) -> str:
    """Extract a stable label from the upstream URL — prefers ``rendition=`` query param."""
    m = _RENDITION_PARAM_RE.search(url)
    if m:
        return m.group(1)
    # Fallback: use a hash of the URL
    import hashlib
    return hashlib.sha1(url.encode()).hexdigest()[:8]


def rewrite_master(text: str, *, session_id: str, base_path: str) -> str:
    """Replace upstream URLs in a master playlist with our proxy paths."""
    out_lines: list[str] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Audio/Subtitle media tags carry URI in attributes
        if line.startswith("#EXT-X-MEDIA:"):
            uri_m = _URI_ATTR_RE.search(line)
            type_m = re.search(r"TYPE=(\w+)", line)
            lang_m = re.search(r'LANGUAGE="([^"]+)"', line)
            if uri_m and type_m and lang_m:
                lang = lang_m.group(1)
                if type_m.group(1) == "AUDIO":
                    new_uri = f"{base_path}/audio/{lang}.m3u8"
                elif type_m.group(1) == "SUBTITLES":
                    new_uri = f"{base_path}/sub/{lang}.vtt"
                else:
                    new_uri = uri_m.group(1)
                line = line[:uri_m.start()] + f'URI="{new_uri}"' + line[uri_m.end():]
            out_lines.append(line)
            i += 1
            continue

        # STREAM-INF is followed by a URI on the next line
        if line.startswith("#EXT-X-STREAM-INF:"):
            out_lines.append(line)
            i += 1
            if i < len(lines):
                upstream_url = lines[i].strip()
                if upstream_url and not upstream_url.startswith("#"):
                    label = _label_for_rendition(upstream_url)
                    out_lines.append(f"{base_path}/video/{label}.m3u8")
                    i += 1
                    continue
            continue

        out_lines.append(line)
        i += 1

    return "\n".join(out_lines)


def rewrite_media(text: str, *, session_id: str, rendition: str, base_path: str) -> str:
    """Replace segment + AES-128 key URIs in a media playlist.

    AES-128 stream encryption keys carry an absolute or relative URI (often
    something like ``/storage/enc.key`` on the upstream origin) that the player
    must fetch. We rewrite that URI to point at our proxy so cookies / origin
    checks don't leak the upstream domain.
    """
    out_lines: list[str] = []
    seg_index = 0
    for line in text.split("\n"):
        # AES-128 key — rewrite URI attribute.
        if line.startswith("#EXT-X-KEY:"):
            new_uri = f"{base_path}/key/{rendition}"
            line = _URI_ATTR_RE.sub(f'URI="{new_uri}"', line, count=1)
            out_lines.append(line)
            continue
        # Segment URLs are non-comment, non-empty lines
        if line and not line.startswith("#"):
            out_lines.append(f"{base_path}/seg/{rendition}/{seg_index}.ts")
            seg_index += 1
            continue
        out_lines.append(line)
    return "\n".join(out_lines)
