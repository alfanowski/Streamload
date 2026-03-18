"""SuperVideo player extractor for Streamload.

Handles extraction of HLS master playlist URLs from the SuperVideo player,
which is used by GuardaSerie, MostraGuarda, and other Italian streaming
services.

The flow:
    1. Fetch the SuperVideo embed page.
    2. Locate the packed JavaScript containing the ``jwplayer().setup()``
       call with the video source URL.
    3. Unpack the JS packer obfuscation.
    4. Parse the ``setup({...})`` JSON to extract the HLS ``file`` URL.
    5. If no packed JS is found, follow iframe chains to locate the player.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from streamload.core.exceptions import ServiceError
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_SERVICE_TAG = "supervideo"


# ---------------------------------------------------------------------------
# JavaScript unpacker (Dean Edwards packer)
# ---------------------------------------------------------------------------

def _unpack(source: str) -> str | None:
    """Unpack a Dean Edwards packed JavaScript string.

    Dean Edwards packer produces code like::

        eval(function(p,a,c,k,...){...}('payload',radix,count,'dict'.split('|')))

    This function reconstructs the original JS by substituting dictionary
    words back into the payload template.

    Returns the unpacked JS string, or ``None`` if the source does not
    contain a recognised packed block.
    """
    match = re.search(
        r"eval\(function\(\w+,\w+,\w+,\w+(?:,\w+,\w+)?\)\{.*?\}\("
        r"'(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)\)\)",
        source,
        re.DOTALL,
    )
    if not match:
        return None

    payload = match.group(1)
    radix = int(match.group(2))
    words = match.group(4).split("|")

    def _replace(m: re.Match[str]) -> str:
        token = m.group(0)
        try:
            index = int(token, radix)
        except ValueError:
            return token
        return words[index] if index < len(words) and words[index] else token

    return re.sub(r"\b\w+\b", _replace, payload)


def _extract_setup_json(js_source: str) -> dict | None:
    """Parse the ``jwplayer().setup({...})`` call and return the config dict.

    The setup object uses JS syntax (unquoted keys, single-quoted strings)
    so we normalise it to valid JSON before parsing.

    Returns the parsed dict, or ``None`` if the setup call is not found.
    """
    m = re.search(r"\.setup\((\{.*?\})\);", js_source, re.DOTALL)
    if not m:
        return None
    raw = m.group(1)

    def _js_to_json(s: str) -> str:
        s = s.replace("\\'", "'")
        result: list[str] = []
        i = 0
        while i < len(s):
            if s[i] == '"':
                # Skip through double-quoted strings.
                j = i + 1
                while j < len(s) and s[j] != '"':
                    if s[j] == "\\":
                        j += 1
                    j += 1
                result.append(s[i : j + 1])
                i = j + 1
            elif s[i] == "'":
                # Convert single-quoted strings to double-quoted.
                j = i + 1
                inner: list[str] = []
                while j < len(s) and s[j] != "'":
                    if s[j] == "\\":
                        j += 1
                    inner.append(s[j])
                    j += 1
                result.append('"' + "".join(inner) + '"')
                i = j + 1
            else:
                result.append(s[i])
                i += 1

        s = "".join(result)
        # Quote unquoted JS object keys.
        s = re.sub(r"(?<=[{,\[])\s*([a-zA-Z_]\w*)\s*:", r'"\1":', s)
        # Remove trailing commas.
        s = re.sub(r",\s*([}\]])", r"\1", s)
        return s

    try:
        return json.loads(_js_to_json(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        log.debug("Failed to parse setup JSON: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_playlist(
    http: HttpClient,
    embed_url: str,
) -> str | None:
    """Extract the HLS master playlist URL from a SuperVideo embed page.

    Walks the following chain:

    1. Fetch the embed URL page.
    2. Look for packed JS (``eval(function(...))``) containing the
       ``jwplayer().setup()`` call.
    3. If no packed JS, look for an iframe and follow it once.
    4. Unpack the JS and extract the ``sources[0].file`` URL from the
       setup config.

    Parameters
    ----------
    http:
        Shared HTTP client.
    embed_url:
        The full SuperVideo embed URL (e.g.
        ``https://supervideo.cc/e/...``).

    Returns
    -------
    str | None
        The HLS master playlist URL, or ``None`` when no playable stream
        can be resolved.
    """
    log.debug("Fetching SuperVideo page: %s", embed_url)

    resp = http.get(embed_url, use_curl=True)
    if resp.status_code >= 400:
        log.error("SuperVideo page returned HTTP %d: %s", resp.status_code, embed_url)
        return None

    playlist = _try_extract_from_html(resp.text)
    if playlist:
        return playlist

    # Fallback: follow the first iframe.
    soup = BeautifulSoup(resp.text, "html.parser")
    iframes = soup.find_all("iframe")
    for iframe in iframes:
        src = iframe.get("src") or iframe.get("data-src")
        if not src:
            continue

        if src.startswith("//"):
            src = "https:" + src

        log.debug("Following SuperVideo iframe: %s", src)
        iframe_resp = http.get(src, use_curl=True)
        if iframe_resp.status_code >= 400:
            continue

        playlist = _try_extract_from_html(iframe_resp.text)
        if playlist:
            return playlist

    log.warning("Could not extract playlist from SuperVideo: %s", embed_url)
    return None


def _try_extract_from_html(html: str) -> str | None:
    """Attempt to extract a playlist URL from raw HTML content.

    Looks for packed JS blocks containing ``eval(function(...))`` and
    unpacks them to find the ``jwplayer().setup()`` call.
    """
    soup = BeautifulSoup(html, "html.parser")

    for script in soup.find_all("script"):
        script_text = script.string or ""
        if "eval" not in script_text:
            continue

        unpacked = _unpack(script_text)
        if not unpacked:
            continue

        setup = _extract_setup_json(unpacked)
        if setup and "sources" in setup:
            sources = setup["sources"]
            if isinstance(sources, list) and sources:
                file_url = sources[0].get("file")
                if file_url:
                    log.debug("Extracted SuperVideo playlist: %s", file_url)
                    return file_url

    return None
