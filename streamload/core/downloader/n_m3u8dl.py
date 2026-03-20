"""N_m3u8DL-RE based HLS/DASH downloader for Streamload.

Uses the N_m3u8DL-RE binary (compiled Go tool) for significantly faster
segment downloads compared to the pure Python HLS downloader. The binary
is auto-downloaded from GitHub on first use.

Falls back to the Python HLS downloader if the binary is unavailable.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from streamload.core.events import (
    DownloadProgress,
    EventCallbacks,
    WarningEvent,
)
from streamload.models.config import DownloadConfig
from streamload.models.stream import SelectedTracks
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger
from streamload.utils.system import SystemChecker

log = get_logger(__name__)

# GitHub release info for auto-download
_GITHUB_REPO = "nilaoda/N_m3u8DL-RE"
_GITHUB_API = "https://api.github.com/repos"
_BINARY_DIR = Path("data/bin")


def _extract_field(text: str, pattern: str) -> str | None:
    """Extract a field from N_m3u8DL-RE progress output using regex."""
    m = re.search(pattern, text)
    return m.group(1) if m else None


def _render_download_ui(
    filename: str,
    vid_pct: float,
    vid_info: str,
    aud_pct: float,
    aud_info: str,
) -> None:
    """Render download progress UI using curses for pixel-perfect alignment."""
    import curses

    try:
        stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(0)
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)    # cyan
            curses.init_pair(2, curses.COLOR_WHITE, -1)    # white
            curses.init_pair(3, curses.COLOR_GREEN, -1)    # green
        except curses.error:
            pass

        h, w = stdscr.getmaxyx()

        CYAN = curses.color_pair(1)
        CYAN_B = curses.color_pair(1) | curses.A_BOLD
        WHITE_B = curses.color_pair(2) | curses.A_BOLD
        GREEN_B = curses.color_pair(3) | curses.A_BOLD
        DIM = curses.A_DIM

        stdscr.erase()

        # Banner centered
        banner = [
            "╔═╗╔╦╗╦═╗╔═╗╔═╗╔╦╗╦  ╔═╗╔═╗╔╦╗",
            "╚═╗ ║ ╠╦╝║╣ ╠═╣║║║║  ║ ║╠═╣ ║║",
            "╚═╝ ╩ ╩╚═╚═╝╩ ╩╩ ╩╩═╝╚═╝╩ ╩═╩╝",
        ]
        for i, line in enumerate(banner):
            x = max((w - len(line)) // 2, 0)
            try:
                stdscr.addstr(1 + i, x, line, CYAN_B)
            except curses.error:
                pass

        # Box dimensions
        box_w = min(w - 4, 70)
        box_x = max((w - box_w) // 2, 1)
        box_y = 5
        bar_w = max(box_w - 22, 15)

        def draw_box_top(y: int, title: str) -> int:
            inner = box_w - 2
            t = f" {title} "
            tl = (inner - len(t)) // 2
            tr = inner - len(t) - tl
            try:
                stdscr.addstr(y, box_x, "╭" + "─" * tl, CYAN_B)
                stdscr.addstr(y, box_x + 1 + tl, t, WHITE_B)
                stdscr.addstr(y, box_x + 1 + tl + len(t), "─" * tr + "╮", CYAN_B)
            except curses.error:
                pass
            return y + 1

        def draw_box_bot(y: int) -> int:
            try:
                stdscr.addstr(y, box_x, "╰" + "─" * (box_w - 2) + "╯", CYAN_B)
            except curses.error:
                pass
            return y + 1

        def draw_box_empty(y: int) -> int:
            try:
                stdscr.addstr(y, box_x, "│", CYAN)
                stdscr.addstr(y, box_x + box_w - 1, "│", CYAN)
            except curses.error:
                pass
            return y + 1

        def draw_bar(y: int, x_start: int, pct: float, bw: int):
            filled = int(bw * pct / 100)
            try:
                stdscr.addstr(y, x_start, "━" * filled, CYAN_B)
                stdscr.addstr(y, x_start + filled, "─" * (bw - filled), DIM)
            except curses.error:
                pass

        y = draw_box_top(box_y, "Download")
        y = draw_box_empty(y)

        # Filename
        fn_x = box_x + max((box_w - len(filename)) // 2, 2)
        try:
            stdscr.addstr(y, box_x, "│", CYAN)
            stdscr.addstr(y, fn_x, filename[:box_w - 4], WHITE_B)
            stdscr.addstr(y, box_x + box_w - 1, "│", CYAN)
        except curses.error:
            pass
        y += 1
        y = draw_box_empty(y)

        # Video progress
        try:
            stdscr.addstr(y, box_x, "│", CYAN)
            stdscr.addstr(y, box_x + 3, "Video", CYAN_B)
            draw_bar(y, box_x + 10, vid_pct, bar_w)
            pct_str = f"{vid_pct:5.1f}%"
            stdscr.addstr(y, box_x + 11 + bar_w, pct_str, WHITE_B)
            stdscr.addstr(y, box_x + box_w - 1, "│", CYAN)
        except curses.error:
            pass
        y += 1

        # Video detail line
        try:
            stdscr.addstr(y, box_x, "│", CYAN)
            # Clean ANSI from vid_info
            clean_info = re.sub(r'\033\[[^m]*m', '', vid_info)
            # Parse parts
            parts = clean_info.strip().split()
            info_x = box_x + 10
            for part in parts:
                if part.endswith("ps") or part.endswith("Bps"):
                    stdscr.addstr(y, info_x, part, GREEN_B)
                elif part.startswith("ETA"):
                    stdscr.addstr(y, info_x, part, DIM)
                else:
                    stdscr.addstr(y, info_x, part, DIM)
                info_x += len(part) + 1
            stdscr.addstr(y, box_x + box_w - 1, "│", CYAN)
        except curses.error:
            pass
        y += 1
        y = draw_box_empty(y)

        # Audio progress
        aud_label = f"Audio ({aud_info})" if aud_info else "Audio"
        try:
            stdscr.addstr(y, box_x, "│", CYAN)
            stdscr.addstr(y, box_x + 3, aud_label, CYAN_B)
            aud_bar_x = box_x + 4 + len(aud_label)
            draw_bar(y, aud_bar_x, aud_pct, bar_w)
            pct_str = f"{aud_pct:5.1f}%"
            stdscr.addstr(y, aud_bar_x + bar_w + 1, pct_str, WHITE_B)
            stdscr.addstr(y, box_x + box_w - 1, "│", CYAN)
        except curses.error:
            pass
        y += 1
        y = draw_box_empty(y)

        # Hint
        try:
            stdscr.addstr(y, box_x, "│", CYAN)
            hint = "q: annulla"
            stdscr.addstr(y, box_x + box_w - 2 - len(hint), hint, DIM)
            stdscr.addstr(y, box_x + box_w - 1, "│", CYAN)
        except curses.error:
            pass
        y += 1
        y = draw_box_empty(y)
        draw_box_bot(y)

        stdscr.refresh()
        curses.endwin()

        # Re-enter alternate screen (curses.endwin exits it)
        sys.stdout.write("\033[?1049h")
        sys.stdout.flush()

    except Exception:
        # If curses fails, just clear and show minimal text
        try:
            curses.endwin()
        except Exception:
            pass


def _get_platform_asset_pattern() -> str:
    """Return a regex pattern matching the correct release asset for this OS."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        if "arm" in machine or "aarch64" in machine:
            return r"osx-arm64"
        return r"osx-x64"
    elif system == "windows":
        return r"win-x64"
    else:
        if "arm" in machine or "aarch64" in machine:
            return r"linux-arm64"
        return r"linux-x64"


def find_binary() -> str | None:
    """Find N_m3u8DL-RE binary on PATH or in local data/bin directory."""
    name = "N_m3u8DL-RE.exe" if platform.system().lower() == "windows" else "N_m3u8DL-RE"

    # 1. System PATH
    path = shutil.which(name)
    if path:
        return path

    # 2. Local binary dir
    local = _BINARY_DIR / name
    if local.is_file():
        return str(local)

    return None


def download_binary(http_client: HttpClient) -> str | None:
    """Download N_m3u8DL-RE from GitHub releases.

    Returns the path to the downloaded binary, or None on failure.
    """
    try:
        log.info("Downloading N_m3u8DL-RE from GitHub...")
        resp = http_client.get(
            f"{_GITHUB_API}/{_GITHUB_REPO}/releases/latest",
            max_retries=2,
        )
        resp.raise_for_status()
        release = resp.json()

        pattern = _get_platform_asset_pattern()
        asset_url = None
        asset_name = ""
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if re.search(pattern, name, re.I) and (name.endswith(".zip") or name.endswith(".tar.gz")):
                asset_url = asset.get("browser_download_url")
                asset_name = name
                break

        if not asset_url:
            log.warning("No matching N_m3u8DL-RE binary for this platform")
            return None

        log.info("Downloading %s", asset_url)
        _BINARY_DIR.mkdir(parents=True, exist_ok=True)
        archive_path = _BINARY_DIR / asset_name
        http_client.download_file(asset_url, archive_path)

        # Extract - handle both .zip and .tar.gz
        if asset_name.endswith(".tar.gz"):
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(_BINARY_DIR)
        else:
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(_BINARY_DIR)
        archive_path.unlink()

        # Find the binary in extracted files
        binary_name = "N_m3u8DL-RE.exe" if platform.system().lower() == "windows" else "N_m3u8DL-RE"
        for f in _BINARY_DIR.rglob(binary_name):
            # Make executable on Unix
            if platform.system().lower() != "windows":
                f.chmod(f.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            # Move to bin dir root if nested
            target = _BINARY_DIR / binary_name
            if f != target:
                shutil.move(str(f), str(target))
            log.info("N_m3u8DL-RE installed at %s", target)
            return str(target)

        log.warning("Binary not found in downloaded archive")
        return None

    except Exception as exc:
        log.error("Failed to download N_m3u8DL-RE: %s", exc)
        return None


class N_m3u8dlDownloader:
    """HLS/DASH downloader using N_m3u8DL-RE binary.

    Builds and runs the N_m3u8DL-RE command as a subprocess, parsing
    stdout for progress updates.
    """

    def __init__(
        self,
        http_client: HttpClient,
        config: DownloadConfig,
        binary_path: str | None = None,
    ) -> None:
        self._http = http_client
        self._config = config
        self._binary = binary_path or find_binary()
        self._ffmpeg = SystemChecker().get_ffmpeg_path() or "ffmpeg"

    @property
    def available(self) -> bool:
        """Check if the binary is available."""
        return self._binary is not None

    def ensure_binary(self) -> bool:
        """Download the binary if not available. Returns True if available after."""
        if self._binary:
            return True
        self._binary = download_binary(self._http)
        return self._binary is not None

    def download(
        self,
        manifest_url: str,
        output_dir: Path,
        filename: str,
        download_id: str,
        callbacks: EventCallbacks,
        extra_headers: dict[str, str] | None = None,
        selected_video: str = "best",
        selected_audio: str = "all",
    ) -> Path | None:
        """Download using N_m3u8DL-RE.

        Parameters
        ----------
        manifest_url:
            URL to the HLS master playlist or DASH MPD.
        output_dir:
            Directory for the output file.
        filename:
            Output filename (without extension).
        download_id:
            Unique download ID for progress tracking.
        callbacks:
            Event callbacks for progress.
        extra_headers:
            Headers to pass to N_m3u8DL-RE (e.g. Referer).
        selected_video:
            Video selection filter (e.g. "best", "1080p").
        selected_audio:
            Audio selection filter (e.g. "all", "best").

        Returns
        -------
        Path | None
            Path to the downloaded file, or None on failure.
        """
        if not self._binary:
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = output_dir / f".tmp_{download_id}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        cmd = self._build_command(
            manifest_url=manifest_url,
            filename=filename,
            output_dir=output_dir,
            tmp_dir=tmp_dir,
            extra_headers=extra_headers or {},
            selected_video=selected_video,
            selected_audio=selected_audio,
        )

        log.info("N_m3u8DL-RE command: %s", " ".join(cmd))

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )

            vid_pct = 0.0
            aud_pct = 0.0
            vid_info = ""
            aud_info = ""
            _render_download_ui(filename, vid_pct, vid_info, aud_pct, aud_info)

            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                if line.startswith("Vid"):
                    pct = _extract_field(line, r"([\d.]+)%")
                    size = _extract_field(line, r"([\d.]+\w+/[\d.]+\w+)")
                    speed = _extract_field(line, r"([\d.]+\w+ps)")
                    eta = _extract_field(line, r"(\d+:\d+:\d+)")
                    if pct:
                        vid_pct = float(pct)
                    vid_info = f"{size or ''} \033[1;32m{speed or ''}\033[0;36m ETA {eta or '--:--:--'}"
                elif line.startswith("Aud"):
                    pct = _extract_field(line, r"([\d.]+)%")
                    lang = _extract_field(line, r"Aud\s+(\w+)")
                    if pct:
                        aud_pct = float(pct)
                    aud_info = lang or ""

                _render_download_ui(filename, vid_pct, vid_info, aud_pct, aud_info)

            proc.wait()

            sys.stdout.write("\033[2J\033[H\033[?25h")
            sys.stdout.flush()

            if proc.returncode != 0:
                log.error("N_m3u8DL-RE exited with code %d", proc.returncode)
                return None

            # Find the output file
            for ext in (".ts", ".mp4", ".mkv", ".m4a"):
                candidate = output_dir / f"{filename}{ext}"
                if candidate.exists():
                    return candidate

            # Check for any file matching filename
            for f in output_dir.iterdir():
                if f.stem == filename and f.is_file():
                    return f

            log.warning("N_m3u8DL-RE completed but output file not found")
            return None

        except FileNotFoundError:
            log.error("N_m3u8DL-RE binary not found: %s", self._binary)
            return None
        except Exception as exc:
            log.error("N_m3u8DL-RE failed: %s", exc)
            return None
        finally:
            # Cleanup tmp dir
            if tmp_dir.exists() and self._config.cleanup_tmp:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def _build_command(
        self,
        manifest_url: str,
        filename: str,
        output_dir: Path,
        tmp_dir: Path,
        extra_headers: dict[str, str],
        selected_video: str,
        selected_audio: str,
    ) -> list[str]:
        """Build the N_m3u8DL-RE command line."""
        cmd = [
            self._binary,
            "--save-name", filename,
            "--save-dir", str(output_dir),
            "--tmp-dir", str(tmp_dir),
            "--ffmpeg-binary-path", self._ffmpeg,
            "--binary-merge",
            "--del-after-done",
            "--auto-subtitle-fix", "false",
            "--check-segments-count", "false",
            "--no-log",
        ]

        cmd.extend(["--select-video", selected_video])
        cmd.extend(["--select-audio", selected_audio])
        cmd.extend(["--drop-subtitle", "all"])

        # Headers
        for key, value in extra_headers.items():
            cmd.extend(["--header", f"{key}: {value}"])

        # Threading - use at least 16 threads for speed
        thread_count = max(self._config.thread_count, 16)
        cmd.extend(["--thread-count", str(thread_count)])
        cmd.append("--concurrent-download")

        # Retry
        if self._config.retry_count > 0:
            cmd.extend(["--download-retry-count", str(min(self._config.retry_count, 5))])

        # Speed limit
        if hasattr(self._config, 'max_speed') and self._config.max_speed:
            cmd.extend(["--max-speed", self._config.max_speed])

        cmd.append(manifest_url)
        return cmd

    @staticmethod
    def _parse_progress(line: str) -> dict[str, Any] | None:
        """Parse N_m3u8DL-RE progress output line.

        Example lines:
            Vid  1920x1080 |  50.00% | 24.99MBps | 99.49MB/1.51GB  | 33/435
        """
        if not any(line.startswith(prefix) for prefix in ("Vid", "Aud", "Sub")):
            return None

        result: dict[str, Any] = {}

        # Percentage
        pct_match = re.search(r"([\d.]+)%", line)
        if pct_match:
            pct = float(pct_match.group(1))
            result["downloaded"] = int(pct)
            result["total"] = 100

        # Speed
        speed_match = re.search(r"([\d.]+)\s*(MB|KB|GB)ps", line, re.I)
        if speed_match:
            val = float(speed_match.group(1))
            unit = speed_match.group(2).upper()
            multiplier = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}.get(unit, 1)
            result["speed_bytes"] = val * multiplier

        # Size
        size_match = re.search(r"([\d.]+)\s*(MB|KB|GB)/([\d.]+)\s*(MB|KB|GB)", line, re.I)
        if size_match:
            def to_bytes(val_s, unit_s):
                v = float(val_s)
                m = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}.get(unit_s.upper(), 1)
                return int(v * m)

            result["downloaded"] = to_bytes(size_match.group(1), size_match.group(2))
            result["total"] = to_bytes(size_match.group(3), size_match.group(4))

        return result if result else None
