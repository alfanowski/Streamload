"""Interactive terminal selector for the Streamload CLI.

Provides keyboard-driven single-select and multi-select menus for track
selection, episode picking, and generic list choices.  Works cross-platform
using :mod:`termios` on Unix and :mod:`msvcrt` on Windows.
"""

from __future__ import annotations

import os
import platform
import re
import sys
from typing import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from streamload.models.media import Episode
from streamload.models.stream import (
    AudioTrack,
    SelectedTracks,
    StreamBundle,
    SubtitleTrack,
    VideoTrack,
)

# ---------------------------------------------------------------------------
# Key constants
# ---------------------------------------------------------------------------

KEY_UP = "up"
KEY_DOWN = "down"
KEY_ENTER = "enter"
KEY_SPACE = "space"
KEY_ESC = "esc"
KEY_Q = "q"
KEY_A = "a"
KEY_N = "n"

# ---------------------------------------------------------------------------
# Cross-platform raw key reading
# ---------------------------------------------------------------------------


def _read_key_unix() -> str:
    """Read a single keypress on Unix (macOS / Linux).

    Uses :mod:`termios` to switch stdin into raw mode for the duration of
    the read.  Handles ANSI escape sequences for arrow keys.
    """
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)

        # Escape sequences
        if ch == "\x1b":
            seq = sys.stdin.read(1)
            if seq == "[":
                code = sys.stdin.read(1)
                if code == "A":
                    return KEY_UP
                if code == "B":
                    return KEY_DOWN
                if code == "C":
                    return "right"
                if code == "D":
                    return "left"
            return KEY_ESC

        if ch == "\r" or ch == "\n":
            return KEY_ENTER
        if ch == " ":
            return KEY_SPACE
        if ch == "\x03":
            # Ctrl-C -- raise so callers see KeyboardInterrupt
            raise KeyboardInterrupt
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _read_key_windows() -> str:
    """Read a single keypress on Windows via :mod:`msvcrt`."""
    import msvcrt

    ch = msvcrt.getwch()

    # Function / arrow keys come as two-char sequences starting with
    # '\x00' or '\xe0'.
    if ch in ("\x00", "\xe0"):
        code = msvcrt.getwch()
        if code == "H":
            return KEY_UP
        if code == "P":
            return KEY_DOWN
        if code == "K":
            return "left"
        if code == "M":
            return "right"
        return ""

    if ch == "\r":
        return KEY_ENTER
    if ch == " ":
        return KEY_SPACE
    if ch == "\x1b":
        return KEY_ESC
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch


_read_key_impl = _read_key_windows if platform.system() == "Windows" else _read_key_unix

# ---------------------------------------------------------------------------
# Range parser  (e.g. "3-7" or "1,4-6,9")
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"^[\d,\s\-]+$")


def _parse_ranges(text: str, max_val: int) -> list[int] | None:
    """Parse a range expression into a sorted list of zero-based indices.

    Accepted formats: ``"3"``, ``"3-7"``, ``"1,4-6,9"``.
    Numbers are 1-based in the input and converted to 0-based in output.
    Returns ``None`` on parse failure.
    """
    text = text.strip()
    if not _RANGE_RE.match(text):
        return None

    indices: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = part.split("-", maxsplit=1)
            try:
                lo = int(bounds[0])
                hi = int(bounds[1])
            except ValueError:
                return None
            if lo < 1 or hi > max_val or lo > hi:
                return None
            indices.update(range(lo - 1, hi))
        else:
            try:
                val = int(part)
            except ValueError:
                return None
            if val < 1 or val > max_val:
                return None
            indices.add(val - 1)

    return sorted(indices) if indices else None


# ---------------------------------------------------------------------------
# InteractiveSelector
# ---------------------------------------------------------------------------


class InteractiveSelector:
    """Interactive multi-select component for the terminal.

    Keyboard bindings:

    * **Up / Down** -- move cursor
    * **Space** -- toggle selection (multi) or select (single)
    * **a** -- select all  (multi mode)
    * **n** -- deselect all (multi mode)
    * **Enter** -- confirm selection
    * **q / Esc** -- cancel and return ``None``

    For episode selection a range string (e.g. ``"3-7"``) can also be typed.
    """

    def __init__(self, console: Console) -> None:
        self._console = console

    # -- Public API --------------------------------------------------------

    def select_tracks(
        self,
        bundle: StreamBundle,
        preferred_audio: str = "",
        preferred_subtitle: str = "",
    ) -> SelectedTracks | None:
        """Interactive track selection across video, audio, and subtitle.

        Shows three successive selection screens:

        1. Video quality -- single select (radio buttons)
        2. Audio tracks  -- multi select  (pre-selected by *preferred_audio*)
        3. Subtitle tracks -- multi select (pre-selected by *preferred_subtitle*)

        Returns a :class:`SelectedTracks` or ``None`` if the user cancels.
        """
        # -- Video (single select) -----------------------------------------
        if not bundle.video:
            self._console.print("[red]No video tracks available.[/red]")
            return None

        video_labels = [t.label for t in bundle.video]
        video_idx = self.select_from_list(
            video_labels, title="Select video quality", multi=False
        )
        if video_idx is None:
            return None
        assert isinstance(video_idx, int)
        selected_video: VideoTrack = bundle.video[video_idx]

        # -- Audio (multi select) ------------------------------------------
        if not bundle.audio:
            selected_audio: list[AudioTrack] = []
        else:
            audio_labels = [t.label for t in bundle.audio]
            audio_preselected = self._preselect_by_language(
                bundle.audio, preferred_audio
            )
            audio_result = self.select_from_list(
                audio_labels,
                title="Select audio tracks",
                multi=True,
                preselected=audio_preselected,
            )
            if audio_result is None:
                return None
            assert isinstance(audio_result, list)
            selected_audio = [bundle.audio[i] for i in audio_result]

        # -- Subtitles (multi select) --------------------------------------
        if not bundle.subtitles:
            selected_subs: list[SubtitleTrack] = []
        else:
            sub_labels = [t.label for t in bundle.subtitles]
            sub_preselected = self._preselect_by_language(
                bundle.subtitles, preferred_subtitle
            )
            sub_result = self.select_from_list(
                sub_labels,
                title="Select subtitle tracks",
                multi=True,
                preselected=sub_preselected,
            )
            if sub_result is None:
                return None
            assert isinstance(sub_result, list)
            selected_subs = [bundle.subtitles[i] for i in sub_result]

        return SelectedTracks(
            video=selected_video,
            audio=selected_audio,
            subtitles=selected_subs,
        )

    def select_episodes(
        self, episodes: list[Episode], title: str = ""
    ) -> list[Episode] | None:
        """Interactive episode selection with range input support.

        Returns a list of selected :class:`Episode` objects or ``None`` if
        cancelled.
        """
        if not episodes:
            self._console.print("[dim]No episodes available.[/dim]")
            return None

        labels = [f"E{ep.number:02d}  {ep.title}" for ep in episodes]
        result = self._select_loop(
            items=labels,
            title=title or "Select episodes",
            multi=True,
            preselected=set(),
            allow_range=True,
        )
        if result is None:
            return None
        return [episodes[i] for i in result]

    def select_from_list(
        self,
        items: list[str],
        title: str = "",
        multi: bool = False,
        preselected: list[int] | None = None,
    ) -> list[int] | int | None:
        """Generic list selector.

        Parameters
        ----------
        items:
            Display labels for each option.
        title:
            Header text shown above the list.
        multi:
            ``True`` for checkboxes (multi-select), ``False`` for radio
            buttons (single-select).
        preselected:
            Zero-based indices that start checked (multi mode only).

        Returns
        -------
        - **single mode**: the selected index, or ``None``
        - **multi mode**: list of selected indices, or ``None``
        """
        initial = set(preselected) if preselected else set()
        result = self._select_loop(
            items=items,
            title=title or "Select",
            multi=multi,
            preselected=initial,
            allow_range=False,
        )
        if result is None:
            return None
        if not multi:
            return result[0] if result else None
        return result

    # -- Core selection loop -----------------------------------------------

    def _select_loop(
        self,
        items: list[str],
        title: str,
        multi: bool,
        preselected: set[int],
        allow_range: bool,
    ) -> list[int] | None:
        """Run the interactive keyboard loop.

        Returns sorted list of selected indices, or ``None`` on cancel.
        """
        if not items:
            return None

        cursor = 0
        selected: set[int] = set(preselected)

        # In single-select mode, start with the first preselected or 0.
        if not multi and selected:
            cursor = min(selected)

        try:
            while True:
                self._render_selection(items, selected, cursor, title, multi)

                key = self._read_key()

                if key == KEY_UP:
                    cursor = (cursor - 1) % len(items)
                elif key == KEY_DOWN:
                    cursor = (cursor + 1) % len(items)
                elif key == KEY_SPACE:
                    if multi:
                        selected ^= {cursor}
                    else:
                        selected = {cursor}
                elif key == KEY_A and multi:
                    selected = set(range(len(items)))
                elif key == KEY_N and multi:
                    selected.clear()
                elif key == KEY_ENTER:
                    if not multi:
                        # In single mode, confirm current cursor position.
                        selected = {cursor}
                    self._clear_selector()
                    return sorted(selected)
                elif key in (KEY_Q, KEY_ESC):
                    self._clear_selector()
                    return None
                elif allow_range and key.isdigit():
                    # Enter range-input mode: collect the full string.
                    range_str = self._collect_range_input(key, items, selected, cursor, title)
                    if range_str is not None:
                        parsed = _parse_ranges(range_str, len(items))
                        if parsed is not None:
                            selected = set(parsed)
        except KeyboardInterrupt:
            self._clear_selector()
            return None

    def _collect_range_input(
        self,
        initial_char: str,
        items: list[str],
        selected: set[int],
        cursor: int,
        title: str,
    ) -> str | None:
        """Collect a range string character-by-character from the user.

        Renders a live preview of the typed range at the bottom of the
        selector. Returns the completed string on Enter, or ``None`` on Esc.
        """
        buf = initial_char
        while True:
            self._render_selection(
                items, selected, cursor, title, multi=True, range_input=buf
            )
            key = self._read_key()
            if key == KEY_ENTER:
                return buf
            if key in (KEY_ESC, KEY_Q):
                return None
            if key == "backspace" or key == "\x7f":
                buf = buf[:-1]
                if not buf:
                    return None
            elif len(key) == 1 and (key.isdigit() or key in "-,"):
                buf += key

    # -- Rendering ---------------------------------------------------------

    def _render_selection(
        self,
        items: list[str],
        selected: set[int],
        cursor: int,
        title: str,
        multi: bool,
        range_input: str | None = None,
    ) -> None:
        """Render the current selection state to the terminal."""
        lines: list[str] = []

        for idx, item in enumerate(items):
            is_cursor = idx == cursor
            is_selected = idx in selected

            # Indicator
            if multi:
                check = "[bold cyan]x[/bold cyan]" if is_selected else " "
                indicator = f"\\[{check}]"
            else:
                check = "[bold cyan]*[/bold cyan]" if is_selected else " "
                indicator = f"({check})"

            # Cursor marker
            prefix = "[bold cyan]>[/bold cyan] " if is_cursor else "  "

            # Number label
            num = f"[dim]{idx + 1:>3}.[/dim]"

            lines.append(f"{prefix}{indicator} {num} {item}")

        content = "\n".join(lines)

        # Footer hints
        if multi:
            hints = (
                "[dim]Space[/dim] toggle  "
                "[dim]a[/dim] all  "
                "[dim]n[/dim] none  "
                "[dim]Enter[/dim] confirm  "
                "[dim]q[/dim] cancel"
            )
        else:
            hints = (
                "[dim]Space[/dim] select  "
                "[dim]Enter[/dim] confirm  "
                "[dim]q[/dim] cancel"
            )

        if range_input is not None:
            hints += f"\n[bold cyan]Range:[/bold cyan] {range_input}"

        footer = f"\n\n{hints}"

        panel = Panel(
            content + footer,
            title=f"[bold]{title}[/bold]",
            border_style="cyan",
            padding=(1, 2),
        )

        # Move cursor to top-left and clear, then print the panel.
        self._console.clear()
        self._console.print(panel)

    def _clear_selector(self) -> None:
        """Clear the selector display."""
        self._console.clear()

    # -- Key reading -------------------------------------------------------

    def _read_key(self) -> str:
        """Read a single keypress from stdin.

        Cross-platform: uses :mod:`termios` on Unix and :mod:`msvcrt` on
        Windows.  Returns a normalized key name (see module constants).
        """
        return _read_key_impl()

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _preselect_by_language(
        tracks: Sequence[AudioTrack] | Sequence[SubtitleTrack],
        preferred: str,
    ) -> list[int]:
        """Return indices of tracks matching the preferred language code."""
        if not preferred:
            return []
        preferred_lower = preferred.lower()
        return [
            i
            for i, t in enumerate(tracks)
            if t.language.lower() == preferred_lower
        ]
