"""Download progress display for the Streamload CLI.

Uses :pymod:`rich.progress` to render concurrent download bars, queue
status, and merge/post-processing stages inside a single live display.
"""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} PB"


# ---------------------------------------------------------------------------
# Main progress UI
# ---------------------------------------------------------------------------


class DownloadProgressUI:
    """Manages download progress bars for concurrent downloads.

    Designed to be used as a context manager::

        with DownloadProgressUI(console) as ui:
            ui.update(event)
    """

    def __init__(self, console: Console) -> None:
        self._console = console
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
        self._tasks: dict[str, int] = {}  # download_id -> rich TaskID
        self._live: Live | None = None
        self._queue_total: int = 0
        self._queue_remaining: int = 0
        self._completed: list[_CompletedEntry] = []
        self._merge_status: dict[str, str] = {}  # download_id -> stage label

    # -- Context manager ----------------------------------------------------

    def __enter__(self) -> DownloadProgressUI:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()

    # -- Lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Start the live progress display."""
        self._live = Live(
            self._build_display(),
            console=self._console,
            refresh_per_second=12,
            transient=False,
        )
        self._live.start()

    def stop(self) -> None:
        """Stop the live progress display and print a summary."""
        if self._live is not None:
            self._live.stop()
            self._live = None

        if self._completed:
            self._print_summary()

    # -- Queue info ---------------------------------------------------------

    def set_queue_info(self, total: int, remaining: int) -> None:
        """Update queue information shown in the header."""
        self._queue_total = total
        self._queue_remaining = remaining
        self._refresh()

    # -- Event handlers -----------------------------------------------------

    def update(self, event: DownloadProgress) -> None:
        """Update progress for a download.

        Creates a new task row if this is the first event for the given
        ``download_id``.
        """
        task_id = self._ensure_task(event.download_id, event.filename, event.total)

        self._progress.update(
            task_id,
            completed=event.downloaded,
            total=event.total or None,
            filename=event.filename,
        )
        self._refresh()

    def complete(self, event: DownloadComplete) -> None:
        """Mark a download as complete and move it to the finished list."""
        task_id = self._tasks.pop(event.download_id, None)
        if task_id is not None:
            self._progress.update(task_id, visible=False)

        # Remove any merge status for this download.
        self._merge_status.pop(event.download_id, None)

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
        task_id = self._tasks.get(event.download_id)
        stage_label = _MERGE_STAGE_LABELS.get(event.stage, event.stage)

        self._merge_status[event.download_id] = stage_label

        if task_id is not None:
            self._progress.update(
                task_id,
                filename=f"{event.filename} [dim]({stage_label})[/dim]",
            )
        self._refresh()

    # -- Internal -----------------------------------------------------------

    def _ensure_task(self, download_id: str, filename: str, total: int) -> int:
        """Return the rich task ID, creating one if needed."""
        if download_id not in self._tasks:
            task_id = self._progress.add_task(
                description="",
                filename=filename,
                total=total or None,
            )
            self._tasks[download_id] = task_id
        return self._tasks[download_id]

    def _build_display(self) -> Panel:
        """Assemble the full live panel: header + progress bars."""
        parts: list[object] = []

        # -- Header with queue info
        if self._queue_total > 0:
            done = self._queue_total - self._queue_remaining
            header = Text()
            header.append("  Queue  ", style="bold white on blue")
            header.append(f"  {done}/{self._queue_total} completed", style="dim")
            if self._queue_remaining > 0:
                header.append(
                    f"  |  {self._queue_remaining} remaining", style="dim cyan"
                )
            parts.append(header)
            parts.append(Text())

        # -- Active progress bars
        parts.append(self._progress)

        # -- Completed items (last 5)
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

            visible = self._completed[-5:]
            for entry in visible:
                completed_table.add_row(
                    "\u2713",
                    _truncate(entry.filepath, 50),
                    _format_size(entry.size),
                    f"{entry.duration:.1f}s",
                )

            if len(self._completed) > 5:
                completed_table.add_row(
                    "",
                    f"[dim]... and {len(self._completed) - 5} more[/dim]",
                    "",
                    "",
                )

            parts.append(completed_table)

        return Panel(
            Group(*parts),
            title="[bold]Streamload[/bold]",
            border_style="blue",
            padding=(1, 2),
        )

    def _refresh(self) -> None:
        """Re-render the live display."""
        if self._live is not None:
            self._live.update(self._build_display())

    def _print_summary(self) -> None:
        """Print a final summary after all downloads complete."""
        total_size = sum(e.size for e in self._completed)
        total_time = max((e.duration for e in self._completed), default=0.0)

        self._console.print()
        summary = Table(
            title="Download Summary",
            title_style="bold white",
            border_style="green",
            show_lines=False,
            padding=(0, 1),
            expand=False,
        )
        summary.add_column("", style="dim", width=16)
        summary.add_column("", style="bold white")

        summary.add_row("Files", str(len(self._completed)))
        summary.add_row("Total size", _format_size(total_size))
        summary.add_row("Duration", f"{total_time:.1f}s")

        self._console.print(summary)
        self._console.print()


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------


class _CompletedEntry:
    """Lightweight record for a finished download."""

    __slots__ = ("download_id", "filepath", "duration", "size")

    def __init__(
        self, download_id: str, filepath: str, duration: float, size: int
    ) -> None:
        self.download_id = download_id
        self.filepath = filepath
        self.duration = duration
        self.size = size


_MERGE_STAGE_LABELS: dict[str, str] = {
    "merging": "Merging tracks",
    "converting_subtitles": "Converting subtitles",
    "generating_nfo": "Generating NFO",
}


def _truncate(text: str, max_len: int) -> str:
    """Truncate a string to *max_len*, adding an ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"
