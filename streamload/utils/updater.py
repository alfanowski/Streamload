"""Auto-update from GitHub releases.

Checks the latest GitHub release for the repository and, when a newer
version is available, downloads and applies it while preserving user
configuration and downloaded data.

Usage::

    from streamload.utils.updater import Updater, UpdateInfo
    from streamload.utils.http import HttpClient

    with HttpClient() as http:
        updater = Updater(http)
        info = updater.check_update()
        if info:
            updater.apply_update(info, project_root=Path("."))
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger
from streamload.version import __repo__, __version__

log = get_logger(__name__)

# Files and directories that must survive an update.
_PRESERVED: frozenset[str] = frozenset({
    "config.json",
    "login.json",
    "data",
})


@dataclass
class UpdateInfo:
    """Metadata about an available update."""

    version: str
    download_url: str
    release_notes: str
    published_at: str


class Updater:
    """Checks for and applies updates from GitHub releases."""

    GITHUB_API = "https://api.github.com"

    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_update(self) -> UpdateInfo | None:
        """Check if a newer version is available on GitHub.

        GET /repos/{repo}/releases/latest

        Compares version strings using :meth:`compare_versions`.
        Returns :class:`UpdateInfo` if a newer version is found,
        ``None`` if the current version is up to date.

        Timeout: uses a single attempt with max_retries=0 so the
        check completes quickly.  Never raises on network failure.
        """
        url = f"{self.GITHUB_API}/repos/{__repo__}/releases/latest"

        try:
            resp = self._http.get(
                url,
                headers={"Accept": "application/vnd.github+json"},
                max_retries=0,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except Exception:  # noqa: BLE001
            log.debug("Update check failed", exc_info=True)
            return None

        tag_name: str = data.get("tag_name", "")
        latest_version = tag_name.lstrip("vV")

        if not latest_version:
            log.debug("GitHub release has no tag_name: %s", data)
            return None

        if not self.compare_versions(__version__, latest_version):
            log.debug(
                "Already up to date: current=%s latest=%s",
                __version__,
                latest_version,
            )
            return None

        # Find the source zip download URL.  Prefer the zipball URL which
        # GitHub always provides for every release.
        download_url: str = data.get("zipball_url", "")
        if not download_url:
            # Fallback: look through release assets for a .zip file.
            for asset in data.get("assets") or []:
                name: str = asset.get("name", "")
                if name.endswith(".zip"):
                    download_url = asset.get("browser_download_url", "")
                    break

        if not download_url:
            log.warning("New version %s found but no download URL", latest_version)
            return None

        release_notes: str = data.get("body") or ""
        published_at: str = data.get("published_at") or ""

        log.info("Update available: %s -> %s", __version__, latest_version)
        return UpdateInfo(
            version=latest_version,
            download_url=download_url,
            release_notes=release_notes,
            published_at=published_at,
        )

    def apply_update(self, info: UpdateInfo, project_root: Path) -> bool:
        """Download and apply the update.

        Workflow:
        1. Download the release zip to a temporary directory.
        2. Extract to a staging area.
        3. Back up current files (except preserved ones).
        4. Copy new files over, skipping preserved paths.
        5. Clean up temporary files.

        Preserves: ``config.json``, ``login.json``, ``data/`` directory.

        Parameters
        ----------
        info:
            The :class:`UpdateInfo` returned by :meth:`check_update`.
        project_root:
            Root directory of the Streamload installation.

        Returns
        -------
        bool
            ``True`` on success, ``False`` on any failure.
        """
        project_root = project_root.resolve()
        log.info("Applying update %s to %s", info.version, project_root)

        tmp_dir: Path | None = None
        backup_dir: Path | None = None

        try:
            # 1. Download -----------------------------------------------
            tmp_dir = Path(tempfile.mkdtemp(prefix="streamload_update_"))
            zip_path = tmp_dir / "release.zip"

            log.info("Downloading release from %s", info.download_url)
            self._http.download_file(info.download_url, zip_path)

            if not zip_path.exists() or zip_path.stat().st_size == 0:
                log.error("Downloaded zip is empty or missing")
                return False

            # 2. Extract -------------------------------------------------
            extract_dir = tmp_dir / "extracted"
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    # Validate: reject archives with path-traversal entries.
                    for member in zf.namelist():
                        resolved = (extract_dir / member).resolve()
                        if not str(resolved).startswith(str(extract_dir.resolve())):
                            log.error("Zip contains suspicious path: %s", member)
                            return False
                    zf.extractall(extract_dir)
            except zipfile.BadZipFile:
                log.error("Downloaded file is not a valid zip archive")
                return False

            # GitHub zipball wraps everything in a single top-level directory
            # (e.g. "user-repo-abc1234/").  Detect and unwrap it.
            source_dir = self._find_source_root(extract_dir)
            if source_dir is None:
                log.error("Could not locate source files in extracted archive")
                return False

            # 3. Back up current files -----------------------------------
            backup_dir = tmp_dir / "backup"
            backup_dir.mkdir()
            self._backup_current(project_root, backup_dir)

            # 4. Copy new files -----------------------------------------
            self._apply_new_files(source_dir, project_root)

            log.info("Update to %s applied successfully", info.version)
            return True

        except Exception:  # noqa: BLE001
            log.error("Update failed, attempting rollback", exc_info=True)
            if backup_dir is not None and backup_dir.exists():
                self._rollback(backup_dir, project_root)
            return False

        finally:
            # 5. Clean up -----------------------------------------------
            if tmp_dir is not None and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def compare_versions(current: str, latest: str) -> bool:
        """Return ``True`` if *latest* is strictly greater than *current*.

        Handles semantic versioning (major.minor.patch) with optional
        pre-release suffixes.  Non-numeric segments are compared
        lexicographically after the numeric parts.

        Examples::

            compare_versions("1.0.0", "1.0.1")   # True
            compare_versions("1.0.1", "1.0.0")   # False
            compare_versions("1.0.0", "1.0.0")   # False
            compare_versions("1.2.3", "2.0.0")   # True
        """
        current_parts = _parse_version(current)
        latest_parts = _parse_version(latest)
        return latest_parts > current_parts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_source_root(extract_dir: Path) -> Path | None:
        """Find the actual source root inside an extracted archive.

        GitHub's zipball nests everything under one directory.  If we
        detect that pattern, return the inner directory.  Otherwise
        return *extract_dir* itself if it contains recognisable project
        files.
        """
        children = list(extract_dir.iterdir())

        # Single top-level directory: unwrap it.
        if len(children) == 1 and children[0].is_dir():
            return children[0]

        # Already at the root (e.g. user-provided zip without wrapper).
        if children:
            return extract_dir

        return None

    @staticmethod
    def _backup_current(project_root: Path, backup_dir: Path) -> None:
        """Copy current project files (excluding preserved) into *backup_dir*."""
        for item in project_root.iterdir():
            if item.name in _PRESERVED:
                continue
            # Skip hidden files and common non-project entries.
            if item.name.startswith("."):
                continue
            dest = backup_dir / item.name
            try:
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            except OSError:
                log.warning("Could not back up %s", item, exc_info=True)

    @staticmethod
    def _apply_new_files(source_dir: Path, project_root: Path) -> None:
        """Copy files from *source_dir* into *project_root*, preserving protected paths."""
        for item in source_dir.iterdir():
            if item.name in _PRESERVED:
                log.debug("Preserving existing %s", item.name)
                continue

            dest = project_root / item.name
            try:
                # Remove existing target first to ensure a clean copy.
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()

                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            except OSError:
                log.error("Failed to install %s", item.name, exc_info=True)

    @staticmethod
    def _rollback(backup_dir: Path, project_root: Path) -> None:
        """Restore backed-up files after a failed update."""
        log.info("Rolling back to previous version")
        for item in backup_dir.iterdir():
            dest = project_root / item.name
            try:
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()

                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            except OSError:
                log.error("Rollback failed for %s", item.name, exc_info=True)


# ----------------------------------------------------------------------
# Version parsing helper
# ----------------------------------------------------------------------

def _parse_version(version: str) -> tuple[tuple[int, ...], str]:
    """Parse a version string into a comparable tuple.

    Returns ``(numeric_parts, pre_release)`` where *numeric_parts* is a
    tuple of ints and *pre_release* is the remaining suffix string.
    A release version (no suffix) sorts higher than a pre-release by
    using ``"~"`` as the release sentinel (``"~" > any printable ascii``
    is false, but we invert: empty suffix means release, so we assign a
    high sentinel).

    ``"1.2.3-beta.1"`` -> ``((1, 2, 3), "beta.1")``
    ``"1.2.3"``        -> ``((1, 2, 3), "~")``
    """
    version = version.strip().lstrip("vV")

    # Split off pre-release: "1.2.3-beta.1" -> "1.2.3", "beta.1"
    pre_release = ""
    for sep in ("-", "+"):
        idx = version.find(sep)
        if idx != -1:
            pre_release = version[idx + 1:]
            version = version[:idx]
            break

    parts: list[int] = []
    for segment in version.split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            # Non-numeric segment: stop parsing numeric portion.
            if not pre_release:
                pre_release = segment
            break

    # Pad to at least 3 elements for consistent comparison.
    while len(parts) < 3:
        parts.append(0)

    # Release versions (no pre-release suffix) sort higher than
    # pre-releases of the same numeric version.
    suffix = pre_release if pre_release else "~"

    return (tuple(parts), suffix)
