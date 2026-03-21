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


def _get_duration(ffmpeg: str, file_path: Path) -> float:
    """Get media duration in seconds using ffmpeg."""
    cmd = [ffmpeg, "-i", str(file_path), "-f", "null", "-"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        # Parse duration from stderr: "Duration: 01:32:15.44"
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", result.stderr)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return 0.0


def _fix_ts_audio(ffmpeg: str, ts_path: Path) -> Path:
    """Convert audio .ts to .m4a with timestamp regeneration.

    Exact same approach as VibraVid: uses genpts+igndts+discardcorrupt
    to rebuild timestamps from scratch. Outputs .m4a (not .mp4).
    """
    m4a_path = ts_path.with_suffix(".m4a")
    cmd = [
        ffmpeg, "-y",
        "-fflags", "+genpts+igndts+discardcorrupt",
        "-avoid_negative_ts", "make_zero",
        "-f", "mpegts",
        "-i", str(ts_path),
        "-c", "copy",
        str(m4a_path),
    ]
    log.info("Fixing audio timestamps: %s -> %s", ts_path.name, m4a_path.name)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and m4a_path.exists() and m4a_path.stat().st_size > 0:
            ts_path.unlink(missing_ok=True)
            return m4a_path
    except Exception as exc:
        log.warning("Audio timestamp fix failed for %s: %s", ts_path.name, exc)
    return ts_path


def _ffmpeg_merge(
    ffmpeg: str,
    video: Path,
    audios: list[Path],
    output: Path,
) -> Path | None:
    """Merge video + audio with ffmpeg. Exact VibraVid approach:

    1. Fix audio .ts timestamps by converting to .m4a
    2. Check duration difference between video and each audio
    3. Use -f mpegts for .ts inputs (critical for correct parsing)
    4. Use -shortest if duration differs by more than 3 seconds
    5. Use -c copy (no re-encoding) with PARAM_FINAL defaults
    """
    # Step 1: Fix audio timestamps
    fixed_audios = []
    for a in audios:
        if a.suffix.lower() == ".ts":
            fixed_audios.append(_fix_ts_audio(ffmpeg, a))
        else:
            fixed_audios.append(a)

    # Step 2: Check duration differences
    use_shortest = False
    vid_duration = _get_duration(ffmpeg, video)
    for af in fixed_audios:
        aud_duration = _get_duration(ffmpeg, af)
        diff = abs(vid_duration - aud_duration)
        log.info("Duration check: video=%.1fs audio=%.1fs diff=%.1fs (%s)",
                 vid_duration, aud_duration, diff, af.name)
        if diff > 3.0:
            use_shortest = True
            log.info("Duration diff > 3s, will use -shortest")

    # Step 3: Build merge command
    cmd = [ffmpeg, "-y"]

    # Video input - force mpegts parser for .ts files
    if video.suffix.lower() == ".ts":
        cmd.extend(["-f", "mpegts"])
    cmd.extend(["-i", str(video)])

    # Audio inputs - force mpegts parser for .ts files
    for af in fixed_audios:
        if af.suffix.lower() == ".ts":
            cmd.extend(["-f", "mpegts"])
        cmd.extend(["-i", str(af)])

    # Map streams
    cmd.extend(["-map", "0:v"])
    for i in range(len(fixed_audios)):
        cmd.extend(["-map", f"{i + 1}:a"])

    # Copy codecs (no re-encoding) - same as VibraVid PARAM_FINAL default
    cmd.extend(["-c", "copy"])

    # Use -shortest if duration mismatch detected
    if use_shortest:
        cmd.extend(["-shortest", "-strict", "experimental"])

    cmd.extend([str(output), "-y"])

    log.info("FFmpeg merge: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0 and output.exists():
            # Cleanup source files
            video.unlink(missing_ok=True)
            for af in fixed_audios:
                af.unlink(missing_ok=True)
            log.info("FFmpeg merge OK: %s (%d bytes)", output, output.stat().st_size)
            return output
        else:
            log.error("FFmpeg merge failed (code %d):\n%s",
                       result.returncode, result.stderr[-800:] if result.stderr else "")
            return None
    except Exception as exc:
        log.error("FFmpeg merge error: %s", exc)
        return None


def _ffmpeg_remux(ffmpeg: str, input_path: Path, output: Path) -> bool:
    """Remux a single .ts file to .mkv with timestamp regeneration."""
    cmd = [
        ffmpeg, "-y",
        "-fflags", "+genpts+igndts+discardcorrupt",
        "-avoid_negative_ts", "make_zero",
        "-f", "mpegts",
        "-i", str(input_path),
        "-c", "copy",
        str(output),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0 and output.exists()
    except Exception:
        return False


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable."""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.1f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _draw_completion_screen(
    stdscr: Any,
    filename: str,
    file_size: int = 0,
    cancelled: bool = False,
) -> None:
    """Draw download completion or cancellation screen."""
    import curses

    CYAN_B = curses.color_pair(1) | curses.A_BOLD
    WHITE_B = curses.color_pair(2) | curses.A_BOLD
    GREEN_B = curses.color_pair(3) | curses.A_BOLD
    DIM = curses.A_DIM

    try:
        h, w = stdscr.getmaxyx()
    except curses.error:
        return

    stdscr.erase()
    for row in range(h):
        try:
            stdscr.move(row, 0)
            stdscr.clrtoeol()
        except curses.error:
            pass

    # Banner
    banner_compact = [
        "╔═╗╔╦╗╦═╗╔═╗╔═╗╔╦╗╦  ╔═╗╔═╗╔╦╗",
        "╚═╗ ║ ╠╦╝║╣ ╠═╣║║║║  ║ ║╠═╣ ║║",
        "╚═╝ ╩ ╩╚═╚═╝╩ ╩╩ ╩╩═╝╚═╝╩ ╩═╩╝",
    ]
    banner_large = [
        "███████╗████████╗██████╗ ███████╗ █████╗ ███╗   ███╗██╗      ██████╗  █████╗ ██████╗ ",
        "██╔════╝╚══██╔══╝██╔══██╗██╔════╝██╔══██╗████╗ ████║██║     ██╔═══██╗██╔══██╗██╔══██╗",
        "███████╗   ██║   ██████╔╝█████╗  ███████║██╔████╔██║██║     ██║   ██║███████║██║  ██║",
        "╚════██║   ██║   ██╔══██╗██╔══╝  ██╔══██║██║╚██╔╝██║██║     ██║   ██║██╔══██║██║  ██║",
        "███████║   ██║   ██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗╚██████╔╝██║  ██║██████╔╝",
        "╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝ ",
    ]
    banner = banner_large if w >= 90 else banner_compact
    for i, bline in enumerate(banner):
        x = max((w - len(bline)) // 2, 0)
        try:
            stdscr.addstr(1 + i, x, bline, CYAN_B)
        except curses.error:
            pass

    banner_end = 1 + len(banner) + 1
    box_w = min(w - 6, 50)
    box_x = max((w - box_w) // 2, 2)

    def safe(y: int, x: int, text: str, attr: int = 0):
        try:
            stdscr.addstr(y, x, text[:w - x - 1], attr)
        except curses.error:
            pass

    if cancelled:
        title = " Annullato "
        status_text = "Download annullato"
        status_attr = curses.color_pair(1) | curses.A_BOLD
    else:
        title = " Completato "
        status_text = "✓ Download completato!"
        status_attr = GREEN_B

    # Box top
    inner = box_w - 2
    tl = (inner - len(title)) // 2
    tr = inner - len(title) - tl
    y = banner_end
    safe(y, box_x, "╭" + "─" * tl, CYAN_B)
    safe(y, box_x + 1 + tl, title, WHITE_B)
    safe(y, box_x + 1 + tl + len(title), "─" * tr + "╮", CYAN_B)
    y += 1

    # Empty
    safe(y, box_x, "│", CYAN_B); safe(y, box_x + box_w - 1, "│", CYAN_B); y += 1

    # Status
    safe(y, box_x, "│", CYAN_B)
    sx = box_x + max((box_w - len(status_text)) // 2, 2)
    safe(y, sx, status_text, status_attr)
    safe(y, box_x + box_w - 1, "│", CYAN_B)
    y += 1

    # Empty
    safe(y, box_x, "│", CYAN_B); safe(y, box_x + box_w - 1, "│", CYAN_B); y += 1

    # Filename
    fn = filename[:box_w - 6]
    safe(y, box_x, "│", CYAN_B)
    safe(y, box_x + max((box_w - len(fn)) // 2, 2), fn, WHITE_B)
    safe(y, box_x + box_w - 1, "│", CYAN_B)
    y += 1

    # File size
    if file_size > 0:
        size_str = _format_size(file_size)
        safe(y, box_x, "│", CYAN_B)
        safe(y, box_x + max((box_w - len(size_str)) // 2, 2), size_str, DIM)
        safe(y, box_x + box_w - 1, "│", CYAN_B)
        y += 1

    # Empty
    safe(y, box_x, "│", CYAN_B); safe(y, box_x + box_w - 1, "│", CYAN_B); y += 1

    # Hint
    if not cancelled:
        hint = "Premi un tasto per continuare"
        safe(y, box_x, "│", CYAN_B)
        safe(y, box_x + max((box_w - len(hint)) // 2, 2), hint, DIM)
        safe(y, box_x + box_w - 1, "│", CYAN_B)
        y += 1

    # Empty
    safe(y, box_x, "│", CYAN_B); safe(y, box_x + box_w - 1, "│", CYAN_B); y += 1

    # Box bottom
    safe(y, box_x, "╰" + "─" * (box_w - 2) + "╯", CYAN_B)

    stdscr.refresh()


def _draw_download_screen(
    stdscr: Any,
    filename: str,
    vid_pct: float,
    vid_size: str,
    vid_speed: str,
    vid_eta: str,
    aud_pct: float,
    aud_info: str,
) -> None:
    """Draw download progress screen on an already-initialized curses window."""
    import curses

    CYAN_B = curses.color_pair(1) | curses.A_BOLD
    CYAN = curses.color_pair(1)
    WHITE_B = curses.color_pair(2) | curses.A_BOLD
    GREEN_B = curses.color_pair(3) | curses.A_BOLD
    DIM = curses.A_DIM

    try:
        h, w = stdscr.getmaxyx()
    except curses.error:
        return

    # Clear entire screen properly
    stdscr.erase()
    for row in range(h):
        try:
            stdscr.move(row, 0)
            stdscr.clrtoeol()
        except curses.error:
            pass

    # Responsive banner (same as selector)
    banner_large = [
        "███████╗████████╗██████╗ ███████╗ █████╗ ███╗   ███╗██╗      ██████╗  █████╗ ██████╗ ",
        "██╔════╝╚══██╔══╝██╔══██╗██╔════╝██╔══██╗████╗ ████║██║     ██╔═══██╗██╔══██╗██╔══██╗",
        "███████╗   ██║   ██████╔╝█████╗  ███████║██╔████╔██║██║     ██║   ██║███████║██║  ██║",
        "╚════██║   ██║   ██╔══██╗██╔══╝  ██╔══██║██║╚██╔╝██║██║     ██║   ██║██╔══██║██║  ██║",
        "███████║   ██║   ██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗╚██████╔╝██║  ██║██████╔╝",
        "╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝ ",
    ]
    banner_compact = [
        "╔═╗╔╦╗╦═╗╔═╗╔═╗╔╦╗╦  ╔═╗╔═╗╔╦╗",
        "╚═╗ ║ ╠╦╝║╣ ╠═╣║║║║  ║ ║╠═╣ ║║",
        "╚═╝ ╩ ╩╚═╚═╝╩ ╩╩ ╩╩═╝╚═╝╩ ╩═╩╝",
    ]
    banner = banner_large if w >= 90 else banner_compact
    for i, bline in enumerate(banner):
        x = max((w - len(bline)) // 2, 0)
        try:
            stdscr.addstr(1 + i, x, bline, CYAN_B)
        except curses.error:
            pass

    banner_end = 1 + len(banner) + 1

    # Box - keep everything well inside terminal width
    box_w = min(w - 6, 68)
    box_x = max((w - box_w) // 2, 2)
    # Fixed layout columns: label(20) + bar + pct(7) + padding(4)
    label_col = 20  # fixed label width
    pct_col = 7     # "  5.1%"
    bar_start = box_x + 3 + label_col
    bar_w = max(box_w - label_col - pct_col - 6, 8)

    def safe(y: int, x: int, text: str, attr: int = 0):
        try:
            stdscr.addstr(y, x, text[:w - x - 1], attr)
        except curses.error:
            pass

    def box_border(y: int):
        safe(y, box_x, "│", CYAN)
        safe(y, box_x + box_w - 1, "│", CYAN)

    def draw_bar(y: int, x_start: int, pct: float, bw: int):
        filled = int(bw * pct / 100)
        safe(y, x_start, "━" * filled, CYAN_B)
        safe(y, x_start + filled, "─" * (bw - filled), DIM)

    # Box top with centered title
    title = " Download "
    inner = box_w - 2
    tl = (inner - len(title)) // 2
    tr = inner - len(title) - tl
    y = banner_end
    safe(y, box_x, "╭" + "─" * tl, CYAN_B)
    safe(y, box_x + 1 + tl, title, WHITE_B)
    safe(y, box_x + 1 + tl + len(title), "─" * tr + "╮", CYAN_B)
    y += 1

    box_border(y); y += 1

    # Filename centered
    fn = filename[:box_w - 6]
    fn_x = box_x + max((box_w - len(fn)) // 2, 2)
    box_border(y)
    safe(y, fn_x, fn, WHITE_B)
    y += 1

    box_border(y); y += 1

    # Video progress - label and bar on same line, fixed columns
    box_border(y)
    safe(y, box_x + 3, "Video", CYAN_B)
    draw_bar(y, bar_start, vid_pct, bar_w)
    safe(y, bar_start + bar_w + 1, f"{vid_pct:5.1f}%", WHITE_B)
    y += 1

    # Video detail
    box_border(y)
    detail_parts = []
    if vid_size:
        detail_parts.append(vid_size)
    if vid_speed:
        detail_parts.append(vid_speed)
    if vid_eta:
        detail_parts.append(f"ETA {vid_eta}")
    detail_x = bar_start
    for i, part in enumerate(detail_parts):
        attr = GREEN_B if ("Bps" in part or "bps" in part) else DIM
        safe(y, detail_x, part, attr)
        detail_x += len(part) + 2
    y += 1

    box_border(y); y += 1

    # Audio progress - same fixed columns as video
    aud_label = f"Audio ({aud_info})" if aud_info else "Audio"
    box_border(y)
    safe(y, box_x + 3, aud_label[:label_col], CYAN_B)
    draw_bar(y, bar_start, aud_pct, bar_w)
    safe(y, bar_start + bar_w + 1, f"{aud_pct:5.1f}%", WHITE_B)
    y += 1

    box_border(y); y += 1

    # Hint
    box_border(y)
    hint = "q: annulla"
    safe(y, box_x + box_w - 2 - len(hint), hint, DIM)
    y += 1

    box_border(y); y += 1

    # Box bottom
    safe(y, box_x, "╰" + "─" * (box_w - 2) + "╯", CYAN_B)

    stdscr.refresh()


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

        import curses

        stdscr = None
        try:
            # Init curses ONCE for the entire download
            stdscr = curses.initscr()
            curses.noecho()
            curses.cbreak()
            curses.curs_set(0)
            try:
                curses.start_color()
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_CYAN, -1)
                curses.init_pair(2, curses.COLOR_WHITE, -1)
                curses.init_pair(3, curses.COLOR_GREEN, -1)
            except curses.error:
                pass

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
            vid_size = ""
            vid_speed = ""
            vid_eta = ""
            aud_info = ""

            # Enable non-blocking key reading for 'q' cancel
            stdscr.nodelay(True)

            _draw_download_screen(stdscr, filename, vid_pct, vid_size, vid_speed, vid_eta, aud_pct, aud_info)

            cancelled = False
            for raw_line in proc.stdout:
                # Check for 'q' cancel
                try:
                    ch = stdscr.getch()
                    if ch == ord('q') or ch == ord('Q'):
                        proc.terminate()
                        cancelled = True
                        break
                except curses.error:
                    pass

                line = raw_line.strip()
                if not line:
                    continue

                if line.startswith("Vid"):
                    pct = _extract_field(line, r"([\d.]+)%")
                    if pct:
                        vid_pct = float(pct)
                    vid_size = _extract_field(line, r"([\d.]+\w+/[\d.]+\w+)") or vid_size
                    vid_speed = _extract_field(line, r"([\d.]+\w+ps)") or vid_speed
                    vid_eta = _extract_field(line, r"(\d+:\d+:\d+)") or vid_eta
                elif line.startswith("Aud"):
                    pct = _extract_field(line, r"([\d.]+)%")
                    lang = _extract_field(line, r"Aud\s+(\w+)")
                    if pct:
                        aud_pct = float(pct)
                    if lang:
                        aud_info = lang

                _draw_download_screen(stdscr, filename, vid_pct, vid_size, vid_speed, vid_eta, aud_pct, aud_info)

            proc.wait()

            if cancelled:
                log.info("Download cancelled by user")
                # Show cancelled message briefly
                _draw_completion_screen(stdscr, filename, cancelled=True)
                import time; time.sleep(1.5)
                curses.endwin()
                stdscr = None
                sys.stdout.write("\033[?1049h\033[2J\033[H")
                sys.stdout.flush()
                return None

            if proc.returncode != 0:
                log.error("N_m3u8DL-RE exited with code %d", proc.returncode)
                curses.endwin()
                stdscr = None
                sys.stdout.write("\033[?1049h\033[2J\033[H")
                sys.stdout.flush()
                return None

            # Find output files - binary-merge produces separate video + audio files
            # e.g. "filename.ts" (video) + "filename.Italian.ts" (audio)
            video_file = None
            audio_files = []

            for f in sorted(output_dir.iterdir()):
                if not f.is_file():
                    continue
                fname = f.name
                stem = f.stem
                # Skip temp/hidden files
                if fname.startswith("."):
                    continue

                if stem == filename and f.suffix in (".ts", ".mp4", ".m4v", ".mkv"):
                    video_file = f
                elif fname.startswith(filename + ".") and f.suffix in (".ts", ".m4a", ".aac", ".mp4"):
                    # Audio files: "filename.Italian.ts", "filename.English.ts"
                    if stem != filename:
                        audio_files.append(f)

            log.info(
                "N_m3u8DL-RE output: video=%s, audio=%s",
                video_file, [f.name for f in audio_files],
            )

            # Mux video + audio with ffmpeg for proper sync
            result_path = None
            if video_file:
                if audio_files:
                    # Merge with ffmpeg using proper sync flags
                    result_path = _ffmpeg_merge(
                        self._ffmpeg, video_file, audio_files,
                        output_dir / f"{filename}.mkv",
                    )
                    # Source files are cleaned up inside _ffmpeg_merge
                else:
                    # No separate audio - audio is embedded in video
                    result_path = video_file
                    # Rename to .mkv if it's .ts
                    if result_path.suffix == ".ts":
                        mkv_path = result_path.with_suffix(".mkv")
                        _ffmpeg_remux(self._ffmpeg, result_path, mkv_path)
                        result_path.unlink(missing_ok=True)
                        result_path = mkv_path

            if result_path is None:
                # Fallback: look for any file matching filename
                for f in output_dir.iterdir():
                    if f.stem == filename and f.is_file() and not f.name.startswith("."):
                        result_path = f
                        break

            # Show completion screen
            file_size = result_path.stat().st_size if result_path and result_path.exists() else 0
            _draw_completion_screen(stdscr, filename, file_size=file_size)
            # Wait for user to press any key
            stdscr.nodelay(False)
            stdscr.getch()

            # Clean exit
            curses.endwin()
            stdscr = None
            sys.stdout.write("\033[?1049h\033[2J\033[H")
            sys.stdout.flush()

            if result_path is None:
                log.warning("N_m3u8DL-RE completed but output file not found")
            return result_path

        except FileNotFoundError:
            log.error("N_m3u8DL-RE binary not found: %s", self._binary)
            return None
        except Exception as exc:
            log.error("N_m3u8DL-RE failed: %s", exc)
            return None
        finally:
            # Always clean up curses
            if stdscr is not None:
                try:
                    curses.endwin()
                except Exception:
                    pass
                sys.stdout.write("\033[?1049h\033[2J\033[H")
                sys.stdout.flush()
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
            "--mp4-real-time-decryption", "false",
            "--no-log",
        ]

        cmd.extend(["--select-video", selected_video])
        cmd.extend(["--select-audio", selected_audio])
        cmd.extend(["--drop-subtitle", "all"])

        # Headers
        for key, value in extra_headers.items():
            cmd.extend(["--header", f"{key}: {value}"])

        # Threading - enough for speed but not so many that CDN rate-limits
        thread_count = max(self._config.thread_count, 8)
        cmd.extend(["--thread-count", str(thread_count)])

        # Do NOT use --concurrent-download. Downloading video and audio
        # simultaneously causes audio to stall on VixCloud CDN due to
        # rate limiting (too many connections). Sequential download is
        # more reliable - video first, then audio.

        # Request timeout - prevent individual segments from hanging forever
        cmd.extend(["--http-request-timeout", "15"])

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
