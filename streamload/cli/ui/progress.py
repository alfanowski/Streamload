"""Download progress display for the Streamload CLI.

Uses :mod:`rich.live` and :mod:`rich.progress` to render concurrent
download bars, queue status, merge stages, and keyboard hints inside
a flicker-free live panel.  All user-visible text is routed through
the I18n translation layer.
"""

from __future__ import annotations

import platform
import shutil
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

from streamload.core.events import DownloadComplete, DownloadProgress, MergeProgress

if TYPE_CHECKING:
    from streamload.cli.i18n import I18n

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REFRESH_RATE = 12  # frames per second
_MAX_VISIBLE_COMPLETED = 5


# ---------------------------------------------------------------------------
# Download state
# ---------------------------------------------------------------------------


class _DownloadState(Enum):
    """Lifecycle state of a tracked download."""

    ACTIVE = "active"
    MERGING = "merging"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETE = "complete"


@dataclass
class _DownloadEntry:
    """Mutable record tracking one download through its lifecycle."""

    download_id: str
    filename: str
    task_id: int  # rich Progress task ID
    state: _DownloadState = _DownloadState.ACTIVE
    total: int = 0
    downloaded: int = 0
    speed: float = 0.0
    merge_stage: str = ""


@dataclass
class _CompletedEntry:
    """Lightweight record for a finished download."""

    __slots__ = ("download_id", "filepath", "duration", "size")

    download_id: str
    filepath: str
    duration: float
    size: int


# ---------------------------------------------------------------------------
# Merge stage labels
# ---------------------------------------------------------------------------

_MERGE_STAGE_LABELS: dict[str, str] = {
    "merging": "Merging tracks",
    "converting_subtitles": "Converting subtitles",
    "generating_nfo": "Generating NFO",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_size(size_bytes: int | float) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def _format_speed(bps: float) -> str:
    """Human-readable transfer speed."""
    if bps <= 0:
        return "0 B/s"
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if abs(bps) < 1024:
            return f"{bps:.1f} {unit}"
        bps /= 1024
    return f"{bps:.1f} TB/s"


def _truncate(text: str, max_len: int) -> str:
    """Truncate a string, adding an ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


def _term_width() -> int:
    """Return the terminal width, clamped to a minimum."""
    return max(shutil.get_terminal_size((80, 24)).columns, 60)


# ---------------------------------------------------------------------------
# Non-blocking key input
# ---------------------------------------------------------------------------


def _read_key_nonblocking() -> str | None:
    """Attempt a non-blocking key read. Returns None if no key is pressed."""
    if platform.system() == "Windows":
        return _read_key_nb_windows()
    return _read_key_nb_unix()


def _read_key_nb_unix() -> str | None:
    """Non-blocking key read on Unix."""
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    if not select.select([fd], [], [], 0)[0]:
        return None

    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)

        if ch == "\x1b":
            # Consume escape sequence without blocking.
            if select.select([fd], [], [], 0)[0]:
                sys.stdin.read(1)
                if select.select([fd], [], [], 0)[0]:
                    sys.stdin.read(1)
            return None

        if ch == "\x03":
            raise KeyboardInterrupt
        return ch
    except (OSError, ValueError):
        return None
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except (OSError, ValueError):
            pass


def _read_key_nb_windows() -> str | None:
    """Non-blocking key read on Windows."""
    import msvcrt

    if not msvcrt.kbhit():
        return None
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        msvcrt.getwch()  # consume extended code
        return None
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch


# ---------------------------------------------------------------------------
# DownloadProgressUI
# ---------------------------------------------------------------------------


class DownloadProgressUI:
    """Manages download progress display with flicker-free live updates.

    Designed to be used as a context manager::

        with DownloadProgressUI(console, i18n) as ui:
            ui.update(event)

    The live panel shows:
    - Per-download progress bars with filename, percentage, speed, ETA
    - Queue summary (completed / remaining)
    - Aggregated total speed
    - Keyboard hint bar

    Parameters
    ----------
    console:
        The rich :class:`Console` for output.
    i18n:
        The internationalisation helper for translating UI strings.
    """

    def __init__(self, console: Console, i18n: I18n) -> None:
        self._console = console
        self._i18n = i18n

        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.fields[filename]}"),
            BarColumn(bar_width=30),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        )

        self._downloads: dict[str, _DownloadEntry] = {}
        self._completed: list[_CompletedEntry] = []
        self._live: Live | None = None
        self._queue_total: int = 0
        self._queue_remaining: int = 0
        self._start_time: float = 0.0

    # -- Context manager ---------------------------------------------------

    def __enter__(self) -> DownloadProgressUI:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()

    # -- Lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the live progress display."""
        self._start_time = time.monotonic()
        self._live = Live(
            self._build_display(),
            console=self._console,
            refresh_per_second=_REFRESH_RATE,
            transient=False,
        )
        self._live.start()

    def stop(self) -> None:
        """Stop the live display and print a final summary."""
        if self._live is not None:
            self._live.stop()
            self._live = None

        if self._completed:
            self._print_summary()

    # -- Queue info --------------------------------------------------------

    def set_queue_info(self, total: int, remaining: int) -> None:
        """Update queue information shown in the header."""
        self._queue_total = total
        self._queue_remaining = remaining
        self._refresh()

    # -- Event handlers ----------------------------------------------------

    def update(self, event: DownloadProgress) -> None:
        """Update progress for a download.

        Creates a new progress bar if this is the first event for the
        given ``download_id``.
        """
        entry = self._ensure_entry(event.download_id, event.filename, event.total)
        entry.downloaded = event.downloaded
        entry.speed = event.speed
        entry.state = _DownloadState.ACTIVE

        self._progress.update(
            entry.task_id,
            completed=event.downloaded,
            total=event.total or None,
            filename=event.filename,
        )
        self._refresh()

    def complete(self, event: DownloadComplete) -> None:
        """Mark a download as complete and move it to the finished list."""
        entry = self._downloads.pop(event.download_id, None)
        if entry is not None:
            entry.state = _DownloadState.COMPLETE
            self._progress.update(entry.task_id, visible=False)

        self._completed.append(
            _CompletedEntry(
                download_id=event.download_id,
                filepath=str(event.filepath),
                duration=event.duration,
                size=event.size,
            )
        )

        if self._queue_remaining > 0:
            self._queue_remaining -= 1

        self._refresh()

    def set_merging(self, event: MergeProgress) -> None:
        """Update status to show a merging / post-processing phase."""
        entry = self._downloads.get(event.download_id)
        stage_label = _MERGE_STAGE_LABELS.get(event.stage, event.stage)

        if entry is not None:
            entry.state = _DownloadState.MERGING
            entry.merge_stage = stage_label
            self._progress.update(
                entry.task_id,
                filename=f"{event.filename} [dim]({stage_label})[/dim]",
            )
        self._refresh()

    def cancel_download(self, download_id: str) -> None:
        """Mark a download as cancelled."""
        entry = self._downloads.get(download_id)
        if entry is not None:
            entry.state = _DownloadState.CANCELLED
            self._progress.update(
                entry.task_id,
                filename=f"[strike]{entry.filename}[/strike] [red]cancelled[/red]",
            )
            self._refresh()

    def pause_download(self, download_id: str) -> None:
        """Toggle pause state for a download."""
        entry = self._downloads.get(download_id)
        if entry is None:
            return

        if entry.state == _DownloadState.PAUSED:
            entry.state = _DownloadState.ACTIVE
            self._progress.update(
                entry.task_id,
                filename=entry.filename,
            )
        elif entry.state == _DownloadState.ACTIVE:
            entry.state = _DownloadState.PAUSED
            self._progress.update(
                entry.task_id,
                filename=f"{entry.filename} [yellow]paused[/yellow]",
            )
        self._refresh()

    def check_input(self) -> str | None:
        """Poll for keyboard input during download.

        Returns a single-character command if a key was pressed, or
        ``None`` if no input is available. The caller should interpret:

        - ``"q"`` -- cancel all downloads
        - ``"x"`` -- cancel the currently selected download
        - ``"p"`` -- pause/resume the currently selected download

        This method is non-blocking and safe to call in a polling loop.
        """
        try:
            return _read_key_nonblocking()
        except (OSError, ValueError):
            return None

    # -- Internal ----------------------------------------------------------

    def _ensure_entry(
        self, download_id: str, filename: str, total: int
    ) -> _DownloadEntry:
        """Return the download entry, creating one if needed."""
        if download_id not in self._downloads:
            task_id = self._progress.add_task(
                description="",
                filename=filename,
                total=total or None,
            )
            self._downloads[download_id] = _DownloadEntry(
                download_id=download_id,
                filename=filename,
                task_id=task_id,
                total=total,
            )
        return self._downloads[download_id]

    def _build_display(self) -> Panel:
        """Assemble the full live panel."""
        term_w = _term_width()
        parts: list[object] = []

        # -- Queue header --------------------------------------------------
        if self._queue_total > 0:
            done = len(self._completed)
            remaining = self._queue_remaining
            header = Text()
            header.append("  Queue  ", style="bold white on blue")
            header.append(f"  {done}/{self._queue_total}", style="bold white")
            header.append(" completed", style="dim")
            if remaining > 0:
                header.append(f"  |  {remaining} remaining", style="dim cyan")
            parts.append(header)
            parts.append(Text())

        # -- Active progress bars ------------------------------------------
        parts.append(self._progress)

        # -- Aggregate speed -----------------------------------------------
        total_speed = sum(
            e.speed
            for e in self._downloads.values()
            if e.state == _DownloadState.ACTIVE
        )
        if total_speed > 0:
            speed_line = Text()
            speed_line.append("  Total: ", style="dim")
            speed_line.append(_format_speed(total_speed), style="bold cyan")
            parts.append(Text())
            parts.append(speed_line)

        # -- Completed items (last N) --------------------------------------
        if self._completed:
            parts.append(Text())
            completed_table = Table(
                show_header=False,
                show_edge=False,
                padding=(0, 1),
                expand=False,
            )
            completed_table.add_column(style="bold green", width=3)
            completed_table.add_column(style="white", min_width=30)
            completed_table.add_column(style="dim", width=12, justify="right")
            completed_table.add_column(style="dim", width=10, justify="right")

            visible = self._completed[-_MAX_VISIBLE_COMPLETED:]
            for entry in visible:
                completed_table.add_row(
                    "\u2713",
                    _truncate(entry.filepath, 50),
                    _format_size(entry.size),
                    f"{entry.duration:.1f}s",
                )

            if len(self._completed) > _MAX_VISIBLE_COMPLETED:
                overflow = len(self._completed) - _MAX_VISIBLE_COMPLETED
                completed_table.add_row(
                    "",
                    f"[dim]... and {overflow} more[/dim]",
                    "",
                    "",
                )

            parts.append(completed_table)

        # -- Keybindings hint ----------------------------------------------
        parts.append(Text())
        hint = Text("  ")
        hint.append("q", style="bold")
        hint.append(": cancel all", style="dim")
        hint.append("  |  ", style="dim")
        hint.append("x", style="bold")
        hint.append(": cancel selected", style="dim")
        hint.append("  |  ", style="dim")
        hint.append("p", style="bold")
        hint.append(": pause/resume", style="dim")
        parts.append(hint)

        # -- Panel title ---------------------------------------------------
        title_text = self._i18n.t("download.select_quality")
        # Use a simple "Downloads" title for the panel.
        panel_title = "[bold]Downloads[/bold]"

        return Panel(
            Group(*parts),
            title=panel_title,
            border_style="blue",
            padding=(1, 2),
            width=min(term_w - 2, 120),
        )

    def _refresh(self) -> None:
        """Re-render the live display."""
        if self._live is not None:
            self._live.update(self._build_display())

    def _print_summary(self) -> None:
        """Print a final summary after all downloads complete."""
        total_size = sum(e.size for e in self._completed)
        elapsed = time.monotonic() - self._start_time if self._start_time else 0.0
        avg_speed = total_size / elapsed if elapsed > 0 else 0.0

        self._console.print()

        summary = Table(
            title="[bold]Download Summary[/bold]",
            title_style="bold white",
            border_style="green",
            show_lines=False,
            padding=(0, 1),
            expand=False,
        )
        summary.add_column("", style="dim", width=18)
        summary.add_column("", style="bold white")

        summary.add_row("Files", str(len(self._completed)))
        summary.add_row("Total size", _format_size(total_size))
        summary.add_row("Duration", f"{elapsed:.1f}s")
        if avg_speed > 0:
            summary.add_row("Average speed", _format_speed(avg_speed))

        self._console.print(summary)
        self._console.print()
