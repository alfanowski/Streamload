"""Extract maximum video resolution from an HLS master playlist."""
from __future__ import annotations

import re
from typing import Optional

_RES_RE = re.compile(r"RESOLUTION=\d+x(\d+)")


def max_height_from_master(text: str) -> Optional[int]:
    """Return the maximum video height found in the HLS master playlist, or None."""
    heights = [int(m.group(1)) for m in _RES_RE.finditer(text)]
    return max(heights) if heights else None
