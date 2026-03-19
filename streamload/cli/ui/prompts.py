"""User input and message prompts for the Streamload CLI.

Provides styled banners, status messages, breadcrumb navigation,
arrow-key confirmations, and text input using rich panels and prompts.
All user-visible text is routed through the I18n translation layer.
"""

from __future__ import annotations

import platform
import shutil
import sys
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

if TYPE_CHECKING:
    from streamload.cli.i18n import I18n

# ---------------------------------------------------------------------------
# ASCII banner -- compact, clean, max 6 lines
# ---------------------------------------------------------------------------

_BANNER_LINES = [
    r" _____ _                            _                 _",
    r"/  ___| |                          | |               | |",
    r"\ `--.| |_ _ __ ___  __ _ _ __ ___ | | ___   __ _  __| |",
    r" `--. \ __| '__/ _ \/ _` | '_ ` _ \| |/ _ \ / _` |/ _` |",
    r"/\__/ / |_| | |  __/ (_| | | | | | | | (_) | (_| | (_| |",
    r"\____/ \__|_|  \___|\__,_|_| |_| |_|_|\___/ \__,_|\__,_|",
]

# ---------------------------------------------------------------------------
# Cross-platform raw key reading (for confirm selector)
# ---------------------------------------------------------------------------


def _read_key() -> str:
    """Read a single keypress, returning a normalised key name."""
    if platform.system() == "Windows":
        return _read_key_windows()
    return _read_key_unix()


def _read_key_unix() -> str:
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)

        if ch == "\x1b":
            seq1 = sys.stdin.read(1)
            if seq1 == "[":
                seq2 = sys.stdin.read(1)
                if seq2 == "A":
                    return "up"
                if seq2 == "B":
                    return "down"
                if seq2 == "C":
                    return "right"
                if seq2 == "D":
                    return "left"
                # Consume extended sequences to avoid junk chars.
                if seq2 in ("1", "2", "3", "4", "5", "6"):
                    sys.stdin.read(1)
            return "esc"

        if ch in ("\r", "\n"):
            return "enter"
        if ch == " ":
            return "space"
        if ch == "\t":
            return "tab"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_key_windows() -> str:
    import msvcrt

    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        code = msvcrt.getwch()
        return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(
            code, ""
        )
    if ch == "\r":
        return "enter"
    if ch == " ":
        return "space"
    if ch == "\x1b":
        return "esc"
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch


# ---------------------------------------------------------------------------
# UIPrompts
# ---------------------------------------------------------------------------


class UIPrompts:
    """User input and confirmation prompts.

    All user-visible text is routed through the :class:`I18n` instance
    so the CLI can display messages in the user's preferred language.

    Parameters
    ----------
    console:
        The rich :class:`Console` used for all output.
    i18n:
        The internationalisation helper for translating string keys.
    """

    def __init__(self, console: Console, i18n: I18n) -> None:
        self._console = console
        self._i18n = i18n

    # -- Banner ------------------------------------------------------------

    def show_banner(self, version: str) -> None:
        """Display a clean ASCII-art Streamload banner with version info."""
        term_width = shutil.get_terminal_size((80, 24)).columns
        banner_text = Text()
        for line in _BANNER_LINES:
            banner_text.append(line, style="bold cyan")
            banner_text.append("\n")

        # Version + tagline line
        banner_text.append("\n")
        banner_text.append(f"  v{version}", style="bold white")
        banner_text.append("  |  ", style="dim")
        banner_text.append("Professional media downloader", style="dim")

        panel = Panel(
            banner_text,
            border_style="cyan",
            padding=(1, 2),
            width=min(term_width - 2, 72),
        )
        self._console.print(panel)

    # -- Breadcrumb navigation ---------------------------------------------

    def show_breadcrumb(self, path: list[str]) -> None:
        """Render a breadcrumb trail below the banner.

        Example output::

            Home > StreamingCommunity > Cars > Quality

        The last item is rendered bold; separators are dim.
        """
        if not path:
            return

        crumb = Text()
        crumb.append("  ")
        for i, segment in enumerate(path):
            is_last = i == len(path) - 1
            if is_last:
                crumb.append(segment, style="bold white")
            else:
                crumb.append(segment, style="dim white")
                crumb.append(" > ", style="dim")

        self._console.print(crumb)
        self._console.print()

    # -- Status messages ---------------------------------------------------

    def show_error(self, message: str) -> None:
        """Display an error message in a red panel."""
        self._console.print()
        self._console.print(
            Panel(
                Text(message, style="bold red"),
                title="[bold red]Error[/bold red]",
                title_align="left",
                border_style="red",
                padding=(0, 1),
            )
        )

    def show_warning(self, message: str) -> None:
        """Display a warning message in yellow with a warning indicator."""
        self._console.print(f"[bold yellow] ![/bold yellow] {message}")

    def show_success(self, message: str) -> None:
        """Display a success message in green with a checkmark."""
        self._console.print(
            f"[bold green] \u2713[/bold green] {message}"
        )

    def show_info(self, message: str) -> None:
        """Display an informational message in blue."""
        self._console.print(f"[blue] i[/blue] [dim]{message}[/dim]")

    # -- Input prompts -----------------------------------------------------

    def confirm(self, message: str, default: bool = True) -> bool:
        """Arrow-key driven Yes/No selector.

        Renders two options inline and lets the user toggle with
        Left/Right arrows or Tab, confirming with Enter.
        """
        selected = default

        try:
            while True:
                self._render_confirm(message, selected)
                key = _read_key()

                if key in ("left", "right", "tab", "up", "down"):
                    selected = not selected
                elif key == "enter":
                    # Clear the selector line and print the final answer.
                    self._clear_lines(2)
                    answer = "Yes" if selected else "No"
                    style = "bold green" if selected else "bold red"
                    self._console.print(
                        f"[bold cyan] ?[/bold cyan] {message} [{style}]{answer}[/{style}]"
                    )
                    return selected
                elif key == "esc":
                    self._clear_lines(2)
                    answer = "Yes" if default else "No"
                    style = "bold green" if default else "bold red"
                    self._console.print(
                        f"[bold cyan] ?[/bold cyan] {message} [{style}]{answer}[/{style}]"
                    )
                    return default
                elif key == "y":
                    selected = True
                elif key == "n":
                    selected = False
        except KeyboardInterrupt:
            self._clear_lines(2)
            return default

    def ask(self, message: str, default: str = "") -> str:
        """Text input with prompt, returning the entered string."""
        return Prompt.ask(
            f"[bold cyan] >[/bold cyan] {message}",
            default=default or None,
            console=self._console,
        ) or ""

    # -- Internal helpers --------------------------------------------------

    def _render_confirm(self, message: str, selected: bool) -> None:
        """Render the inline Yes/No selector."""
        line = Text()
        line.append(" ? ", style="bold cyan")
        line.append(f"{message}  ")

        if selected:
            line.append(" Yes ", style="bold white on cyan")
            line.append("  ")
            line.append(" No ", style="dim")
        else:
            line.append(" Yes ", style="dim")
            line.append("  ")
            line.append(" No ", style="bold white on red")

        line.append("  ", style="dim")
        line.append("\u2190\u2192 toggle  Enter confirm", style="dim")

        # Move cursor up and overwrite.
        self._clear_lines(2)
        self._console.print(line)

    def _clear_lines(self, count: int) -> None:
        """Move cursor up *count* lines and clear them.

        Uses ANSI escape codes for flicker-free updates. Falls back
        to a no-op on platforms without ANSI support.
        """
        if self._console.is_terminal:
            for _ in range(count):
                self._console.file.write("\033[A\033[2K")
            self._console.file.flush()
