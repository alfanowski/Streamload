"""Health and version endpoints."""
from __future__ import annotations

import os
import subprocess

from fastapi import APIRouter

router = APIRouter(tags=["health"])


def _git_sha() -> str:
    if env := os.environ.get("STREAMLOAD_GIT_SHA"):
        return env
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True,
        ).strip()
    except Exception:
        return "unknown"


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    from streamload.version import __version__
    return {"status": "ok", "version": __version__}


@router.get("/version")
async def version() -> dict[str, str]:
    """Detailed version info."""
    from streamload.version import __version__
    return {"version": __version__, "git_sha": _git_sha()}
