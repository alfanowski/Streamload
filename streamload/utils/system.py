"""System dependency checker for Streamload.

Validates that required external tools (FFmpeg, FFprobe) are installed
and reachable before the application starts heavy work.  Provides
OS-specific installation hints when a dependency is missing.

Usage::

    from streamload.utils.system import SystemChecker

    checker = SystemChecker()
    results = checker.verify_all()
    for r in results:
        print(f"{r.name}: {'OK' if r.found else 'MISSING'}")
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from streamload.utils.logger import get_logger

log = get_logger(__name__)

# Minimum supported Python version.
_MIN_PYTHON: tuple[int, int] = (3, 10)

# Common installation locations checked when ``shutil.which`` fails.
_FFMPEG_FALLBACK_PATHS: dict[str, list[str]] = {
    "macos": [
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ],
    "linux": [
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/snap/bin/ffmpeg",
    ],
    "windows": [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
    ],
}

_FFPROBE_FALLBACK_PATHS: dict[str, list[str]] = {
    "macos": [
        "/opt/homebrew/bin/ffprobe",
        "/usr/local/bin/ffprobe",
    ],
    "linux": [
        "/usr/bin/ffprobe",
        "/usr/local/bin/ffprobe",
        "/snap/bin/ffprobe",
    ],
    "windows": [
        r"C:\ffmpeg\bin\ffprobe.exe",
        r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffprobe.exe",
    ],
}

# Installation instructions by OS.
_INSTALL_INSTRUCTIONS: dict[str, dict[str, str]] = {
    "ffmpeg": {
        "macos": "brew install ffmpeg",
        "linux": "sudo apt install ffmpeg   # Debian/Ubuntu\nsudo dnf install ffmpeg   # Fedora",
        "windows": "winget install ffmpeg",
    },
    "ffprobe": {
        "macos": "brew install ffmpeg   # ffprobe is included with ffmpeg",
        "linux": "sudo apt install ffmpeg   # ffprobe is included with ffmpeg",
        "windows": "winget install ffmpeg   # ffprobe is included with ffmpeg",
    },
    "python": {
        "macos": "brew install python@3.10",
        "linux": "sudo apt install python3.10   # Debian/Ubuntu\nsudo dnf install python3.10   # Fedora",
        "windows": "winget install Python.Python.3.10",
    },
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Outcome of a single dependency check.

    Attributes
    ----------
    name:
        Human-readable dependency name (e.g. ``"FFmpeg"``).
    found:
        ``True`` when the dependency is available.
    version:
        Detected version string, or ``None``.
    path:
        Absolute path to the binary, or ``None``.
    message:
        Help text shown to the user when the dependency is missing.
    """

    name: str
    found: bool
    version: str | None = None
    path: str | None = None
    message: str | None = None


# ---------------------------------------------------------------------------
# Checker implementation
# ---------------------------------------------------------------------------

class SystemChecker:
    """Validates system dependencies before the application starts.

    Each ``check_*`` method returns a :class:`CheckResult`.  Call
    :meth:`verify_all` to run every check at once and get a summary list.
    """

    # -- Python -------------------------------------------------------------

    def check_python_version(self) -> CheckResult:
        """Verify that the running Python interpreter meets the minimum version."""
        current = sys.version_info[:2]
        version_str = f"{current[0]}.{current[1]}.{sys.version_info[2]}"
        path = sys.executable

        if current >= _MIN_PYTHON:
            log.info("Python %s found at %s", version_str, path)
            return CheckResult(
                name="Python",
                found=True,
                version=version_str,
                path=path,
            )

        msg = (
            f"Python {_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}+ is required "
            f"(found {version_str}).\n"
            f"Install: {self.get_install_instructions('python')}"
        )
        log.warning("Python version too old: %s", version_str)
        return CheckResult(
            name="Python",
            found=False,
            version=version_str,
            path=path,
            message=msg,
        )

    # -- FFmpeg / FFprobe ---------------------------------------------------

    def check_ffmpeg(self) -> CheckResult:
        """Check that FFmpeg is installed and determine its version."""
        return self._check_binary(
            name="FFmpeg",
            binary="ffmpeg",
            fallback_paths=_FFMPEG_FALLBACK_PATHS,
        )

    def check_ffprobe(self) -> CheckResult:
        """Check that FFprobe is installed."""
        return self._check_binary(
            name="FFprobe",
            binary="ffprobe",
            fallback_paths=_FFPROBE_FALLBACK_PATHS,
        )

    # -- Aggregate ----------------------------------------------------------

    def verify_all(self) -> list[CheckResult]:
        """Run every dependency check and return the collected results.

        FFprobe is treated as optional -- if FFmpeg is found (including
        via imageio-ffmpeg), FFprobe is assumed available since all
        probing operations can be done with ``ffmpeg -i``.
        """
        results = [self.check_python_version()]

        ffmpeg_result = self.check_ffmpeg()
        results.append(ffmpeg_result)

        # If ffmpeg was found via imageio-ffmpeg, skip the separate
        # ffprobe check since the bundled binary handles probing too.
        if ffmpeg_result.found:
            ffprobe_result = self.check_ffprobe()
            if not ffprobe_result.found:
                # Mark as found -- ffmpeg -i covers probing needs.
                ffprobe_result = CheckResult(
                    name="FFprobe",
                    found=True,
                    version=ffmpeg_result.version,
                    path=ffmpeg_result.path,
                    message="Using FFmpeg for probing (ffprobe not separately installed)",
                )
            results.append(ffprobe_result)
        else:
            results.append(self.check_ffprobe())

        passed = sum(1 for r in results if r.found)
        total = len(results)
        log.info("System check: %d/%d dependencies satisfied", passed, total)

        return results

    # -- Path helpers -------------------------------------------------------

    def get_ffmpeg_path(self) -> str | None:
        """Return the absolute path to the FFmpeg binary, or ``None``."""
        return self._locate_binary("ffmpeg", _FFMPEG_FALLBACK_PATHS)

    def get_ffprobe_path(self) -> str | None:
        """Return the absolute path to the FFprobe binary, or ``None``."""
        return self._locate_binary("ffprobe", _FFPROBE_FALLBACK_PATHS)

    # -- Static utilities ---------------------------------------------------

    @staticmethod
    def get_os() -> str:
        """Return a normalised OS identifier: ``'windows'``, ``'macos'``, or ``'linux'``."""
        system = platform.system().lower()
        if system == "darwin":
            return "macos"
        if system == "windows":
            return "windows"
        # Everything else (Linux, FreeBSD, ...) treated as "linux".
        return "linux"

    @staticmethod
    def get_install_instructions(tool: str) -> str:
        """Return OS-specific installation instructions for *tool*.

        Parameters
        ----------
        tool:
            One of ``"ffmpeg"``, ``"ffprobe"``, or ``"python"``
            (case-insensitive).

        Returns
        -------
        str
            Shell command(s) the user can paste to install the tool on
            their current operating system.
        """
        key = tool.lower()
        current_os = SystemChecker.get_os()
        instructions = _INSTALL_INSTRUCTIONS.get(key, {})
        return instructions.get(current_os, f"Please install {tool} manually.")

    # -- Internal -----------------------------------------------------------

    @staticmethod
    def _locate_binary(
        binary: str,
        fallback_paths: dict[str, list[str]],
    ) -> str | None:
        """Find a binary on ``$PATH``, via imageio-ffmpeg, or in well-known fallback locations.

        Returns the first valid path found, or ``None``.
        """
        # 1. Try the standard PATH lookup.
        path = shutil.which(binary)
        if path is not None:
            return path

        # 2. Try imageio-ffmpeg bundled binary (installed via pip).
        if binary in ("ffmpeg", "ffprobe"):
            try:
                import imageio_ffmpeg
                bundled = imageio_ffmpeg.get_ffmpeg_exe()
                if bundled and Path(bundled).is_file():
                    if binary == "ffmpeg":
                        return bundled
                    # ffprobe is in the same directory as ffmpeg
                    ffprobe_path = Path(bundled).parent / ("ffprobe" + Path(bundled).suffix)
                    if ffprobe_path.is_file():
                        return str(ffprobe_path)
            except (ImportError, Exception):
                pass

        # 3. Probe OS-specific fallback paths.
        current_os = SystemChecker.get_os()
        for candidate in fallback_paths.get(current_os, []):
            if Path(candidate).is_file():
                return candidate

        return None

    @staticmethod
    def _get_binary_version(binary_path: str) -> str | None:
        """Run ``<binary> -version`` and parse the first-line version number.

        Returns something like ``"6.1.1"`` or ``None`` on failure.
        """
        try:
            result = subprocess.run(
                [binary_path, "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return None
            first_line = result.stdout.strip().splitlines()[0]
            # Typical first line:
            #   ffmpeg version 6.1.1 Copyright (c) ...
            #   ffprobe version 6.1.1 Copyright (c) ...
            match = re.search(r"version\s+([\w.\-]+)", first_line)
            return match.group(1) if match else first_line
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            log.debug("Could not determine version for %s: %s", binary_path, exc)
            return None

    def _check_binary(
        self,
        name: str,
        binary: str,
        fallback_paths: dict[str, list[str]],
    ) -> CheckResult:
        """Generic binary check: locate, get version, build result."""
        path = self._locate_binary(binary, fallback_paths)

        if path is None:
            msg = (
                f"{name} not found on this system.\n"
                f"Install: {self.get_install_instructions(binary)}"
            )
            log.warning("%s not found", name)
            return CheckResult(name=name, found=False, message=msg)

        version = self._get_binary_version(path)
        log.info("%s %s found at %s", name, version or "(unknown version)", path)

        return CheckResult(
            name=name,
            found=True,
            version=version,
            path=path,
        )
