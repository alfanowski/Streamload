"""Interactive terminal selector for the Streamload CLI.

FZF-style keyboard-driven selector with fuzzy filtering, scrollable windows,
multi-select, and an all-in-one track selection screen.  Works cross-platform
using :mod:`termios` on Unix and :mod:`msvcrt` on Windows.

Exports :class:`InteractiveSelector` with three public methods:

- ``select_from_list``  -- single-select with fuzzy filter
- ``select_episodes``   -- multi-select with range support
- ``select_tracks``     -- unified video/audio/subtitle picker
"""

from __future__ import annotations

import platform
import re
import shutil
import sys
from dataclasses import dataclass, field
from typing import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from streamload.models.media import Episode, MediaType
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
KEY_TAB = "tab"
KEY_SHIFT_TAB = "shift_tab"
KEY_BACKSPACE = "backspace"
KEY_PAGE_UP = "page_up"
KEY_PAGE_DOWN = "page_down"
KEY_HOME = "home"
KEY_END = "end"

# Single-character key names returned verbatim.
KEY_Q = "q"
KEY_A = "a"
KEY_N = "n"

# ---------------------------------------------------------------------------
# Cross-platform raw key reading
# ---------------------------------------------------------------------------


def _read_key_unix() -> str:
    """Read a single keypress on Unix (macOS / Linux).

    Uses :mod:`termios` to switch stdin into raw mode for the duration of
    the read.  Handles ANSI escape sequences for arrow keys, Page Up/Down,
    Home/End, and Shift-Tab.
    """
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
                # Arrow keys
                if seq2 == "A":
                    return KEY_UP
                if seq2 == "B":
                    return KEY_DOWN
                if seq2 == "C":
                    return "right"
                if seq2 == "D":
                    return "left"
                # Home / End (some terminals)
                if seq2 == "H":
                    return KEY_HOME
                if seq2 == "F":
                    return KEY_END
                # Extended sequences: Page Up/Down, Home/End, etc.
                if seq2 in ("1", "2", "3", "4", "5", "6"):
                    seq3 = sys.stdin.read(1)
                    if seq3 == "~":
                        return {
                            "1": KEY_HOME,
                            "2": "insert",
                            "3": "delete",
                            "4": KEY_END,
                            "5": KEY_PAGE_UP,
                            "6": KEY_PAGE_DOWN,
                        }.get(seq2, "")
                    # Shift+Arrow: \x1b[1;2A etc.
                    if seq2 == "1" and seq3 == ";":
                        _mod = sys.stdin.read(1)
                        _code = sys.stdin.read(1)
                        return ""
                if seq2 == "Z":
                    return KEY_SHIFT_TAB
            elif seq1 == "O":
                seq2 = sys.stdin.read(1)
                if seq2 == "H":
                    return KEY_HOME
                if seq2 == "F":
                    return KEY_END
                if seq2 == "Z":
                    return KEY_SHIFT_TAB
            return KEY_ESC

        if ch == "\r" or ch == "\n":
            return KEY_ENTER
        if ch == " ":
            return KEY_SPACE
        if ch == "\t":
            return KEY_TAB
        if ch == "\x7f" or ch == "\x08":
            return KEY_BACKSPACE
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_key_windows() -> str:
    """Read a single keypress on Windows via :mod:`msvcrt`."""
    import msvcrt

    ch = msvcrt.getwch()

    if ch in ("\x00", "\xe0"):
        code = msvcrt.getwch()
        _MAP = {
            "H": KEY_UP,
            "P": KEY_DOWN,
            "K": "left",
            "M": "right",
            "I": KEY_PAGE_UP,
            "Q": KEY_PAGE_DOWN,
            "G": KEY_HOME,
            "O": KEY_END,
        }
        return _MAP.get(code, "")

    if ch == "\r":
        return KEY_ENTER
    if ch == " ":
        return KEY_SPACE
    if ch == "\t":
        return KEY_TAB
    if ch == "\x1b":
        return KEY_ESC
    if ch == "\x08":
        return KEY_BACKSPACE
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch


_read_key = (
    _read_key_windows if platform.system() == "Windows" else _read_key_unix
)

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
                lo, hi = int(bounds[0]), int(bounds[1])
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
# Fuzzy match helper
# ---------------------------------------------------------------------------


def _fuzzy_match(query: str, text: str) -> bool:
    """Return True if every character of *query* appears in *text* in order.

    Case-insensitive.  An empty query matches everything.
    """
    if not query:
        return True
    q = query.lower()
    t = text.lower()
    qi = 0
    for ch in t:
        if ch == q[qi]:
            qi += 1
            if qi == len(q):
                return True
    return False


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------

# Media-type badge colours.
_BADGE_STYLES: dict[str, tuple[str, str]] = {
    "FILM": ("bold white on blue", " FILM "),
    "SERIE": ("bold white on magenta", " SERIE "),
    "ANIME": ("bold white on red", " ANIME "),
}

# Minimum terminal dimensions.
_MIN_WIDTH = 60
_MIN_HEIGHT = 16


def _term_size() -> tuple[int, int]:
    """Return (columns, lines) clamped to minimums."""
    sz = shutil.get_terminal_size((80, 24))
    return max(sz.columns, _MIN_WIDTH), max(sz.lines, _MIN_HEIGHT)


# ---------------------------------------------------------------------------
# Internal state containers
# ---------------------------------------------------------------------------


@dataclass
class _ListState:
    """Mutable state for a scrollable, filterable list."""

    items: list[str]
    cursor: int = 0
    scroll_offset: int = 0
    selected: set[int] = field(default_factory=set)
    filter_text: str = ""
    # Indices into *items* that match the current filter.
    filtered_indices: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.refilter()

    def refilter(self) -> None:
        if self.filter_text:
            self.filtered_indices = [
                i
                for i, item in enumerate(self.items)
                if _fuzzy_match(self.filter_text, item)
            ]
        else:
            self.filtered_indices = list(range(len(self.items)))
        # Clamp cursor.
        if self.filtered_indices:
            self.cursor = min(self.cursor, len(self.filtered_indices) - 1)
            self.cursor = max(self.cursor, 0)
        else:
            self.cursor = 0
        self._fix_scroll()

    @property
    def visible_count(self) -> int:
        return len(self.filtered_indices)

    def real_index(self, filtered_pos: int) -> int:
        """Map a position in the filtered list to the real item index."""
        return self.filtered_indices[filtered_pos]

    def cursor_real(self) -> int | None:
        """Real index at cursor, or None if list empty."""
        if not self.filtered_indices:
            return None
        return self.filtered_indices[self.cursor]

    def move_cursor(self, delta: int, page_size: int) -> None:
        if not self.filtered_indices:
            return
        self.cursor = max(0, min(len(self.filtered_indices) - 1, self.cursor + delta))
        self._fix_scroll(page_size)

    def _fix_scroll(self, page_size: int = 0) -> None:
        if page_size <= 0:
            return
        if self.cursor < self.scroll_offset:
            self.scroll_offset = self.cursor
        elif self.cursor >= self.scroll_offset + page_size:
            self.scroll_offset = self.cursor - page_size + 1
        max_offset = max(0, len(self.filtered_indices) - page_size)
        self.scroll_offset = min(self.scroll_offset, max_offset)

    def toggle(self, pos: int | None = None) -> None:
        idx = self.cursor_real() if pos is None else pos
        if idx is None:
            return
        self.selected ^= {idx}

    def select_all(self) -> None:
        self.selected = set(self.filtered_indices)

    def deselect_all(self) -> None:
        self.selected.clear()


@dataclass
class _TrackSections:
    """State for the all-in-one track selector."""

    video: _ListState
    audio: _ListState
    subtitles: _ListState
    active_section: int = 0  # 0=video, 1=audio, 2=subtitles

    @property
    def active(self) -> _ListState:
        return [self.video, self.audio, self.subtitles][self.active_section]

    @property
    def section_name(self) -> str:
        return ["VIDEO", "AUDIO", "SUBTITLES"][self.active_section]

    def next_section(self) -> None:
        self.active_section = (self.active_section + 1) % 3

    def prev_section(self) -> None:
        self.active_section = (self.active_section - 1) % 3


# ---------------------------------------------------------------------------
# InteractiveSelector
# ---------------------------------------------------------------------------


class InteractiveSelector:
    """FZF-style interactive selector for the Streamload CLI.

    Keyboard bindings (common):

    * **Up / Down**   -- move cursor
    * **Page Up/Down** -- scroll by page
    * **Home / End**   -- jump to first / last
    * **Enter**        -- confirm
    * **Esc**          -- clear filter (1st press) or cancel (2nd press)
    * **q**            -- cancel (when filter is empty)
    * **typing**       -- fuzzy filter

    Multi-select additions:

    * **Space** -- toggle item
    * **a**     -- select all visible
    * **n**     -- deselect all

    Track selector additions:

    * **Tab / Shift-Tab** -- cycle sections
    """

    def __init__(self, console: Console) -> None:
        self._console = console

    # =====================================================================
    # Public API
    # =====================================================================

    def select_from_list(
        self,
        items: list[str],
        title: str = "",
        show_type_badge: bool = False,
    ) -> int | None:
        """Single-select from a list with FZF-style fuzzy filtering.

        Parameters
        ----------
        items:
            Display labels for each option.
        title:
            Header text shown above the list.
        show_type_badge:
            If ``True``, attempt to parse ``[FILM]``/``[SERIE]``/``[ANIME]``
            prefixes from item strings and render coloured badges.

        Returns
        -------
        The selected index, or ``None`` if cancelled.
        """
        if not items:
            return None

        state = _ListState(items=list(items))
        page = self._page_size()

        try:
            while True:
                self._render_list(state, title, page, multi=False, badge=show_type_badge)
                key = _read_key()

                if key == KEY_UP:
                    state.move_cursor(-1, page)
                elif key == KEY_DOWN:
                    state.move_cursor(1, page)
                elif key == KEY_PAGE_UP:
                    state.move_cursor(-page, page)
                elif key == KEY_PAGE_DOWN:
                    state.move_cursor(page, page)
                elif key == KEY_HOME:
                    state.move_cursor(-len(state.filtered_indices), page)
                elif key == KEY_END:
                    state.move_cursor(len(state.filtered_indices), page)
                elif key == KEY_ENTER:
                    self._clear()
                    return state.cursor_real()
                elif key == KEY_ESC:
                    if state.filter_text:
                        state.filter_text = ""
                        state.refilter()
                    else:
                        self._clear()
                        return None
                elif key == KEY_BACKSPACE:
                    if state.filter_text:
                        state.filter_text = state.filter_text[:-1]
                        state.refilter()
                elif key == KEY_Q and not state.filter_text:
                    self._clear()
                    return None
                elif len(key) == 1 and key.isprintable():
                    state.filter_text += key
                    state.refilter()
        except KeyboardInterrupt:
            self._clear()
            return None

    def select_episodes(
        self,
        episodes: list[Episode],
        title: str = "",
    ) -> list[Episode] | None:
        """Multi-select episodes with fuzzy filter and range support.

        Returns a list of selected :class:`Episode` objects or ``None``
        if cancelled.
        """
        if not episodes:
            self._console.print("[dim]No episodes available.[/dim]")
            return None

        labels = [f"E{ep.number:02d}  {ep.title}" for ep in episodes]
        state = _ListState(items=labels)
        page = self._page_size()

        try:
            while True:
                self._render_list(
                    state,
                    title or "Select episodes",
                    page,
                    multi=True,
                    show_count=True,
                )
                key = _read_key()

                if key == KEY_UP:
                    state.move_cursor(-1, page)
                elif key == KEY_DOWN:
                    state.move_cursor(1, page)
                elif key == KEY_PAGE_UP:
                    state.move_cursor(-page, page)
                elif key == KEY_PAGE_DOWN:
                    state.move_cursor(page, page)
                elif key == KEY_HOME:
                    state.move_cursor(-len(state.filtered_indices), page)
                elif key == KEY_END:
                    state.move_cursor(len(state.filtered_indices), page)
                elif key == KEY_SPACE:
                    state.toggle()
                elif key == KEY_A and not state.filter_text:
                    state.select_all()
                elif key == KEY_N and not state.filter_text:
                    state.deselect_all()
                elif key == KEY_ENTER:
                    self._clear()
                    if not state.selected:
                        return None
                    indices = sorted(state.selected)
                    return [episodes[i] for i in indices]
                elif key == KEY_ESC:
                    if state.filter_text:
                        state.filter_text = ""
                        state.refilter()
                    else:
                        self._clear()
                        return None
                elif key == KEY_BACKSPACE:
                    if state.filter_text:
                        state.filter_text = state.filter_text[:-1]
                        state.refilter()
                elif key == KEY_Q and not state.filter_text:
                    self._clear()
                    return None
                elif len(key) == 1 and key.isprintable():
                    state.filter_text += key
                    state.refilter()
                    # Check if the accumulated filter looks like a range.
                    if _RANGE_RE.match(state.filter_text):
                        parsed = _parse_ranges(state.filter_text, len(episodes))
                        if parsed is not None:
                            state.selected = set(parsed)
        except KeyboardInterrupt:
            self._clear()
            return None

    def select_tracks(
        self,
        bundle: StreamBundle,
        preferred_audio: str = "",
        preferred_subtitle: str = "",
    ) -> SelectedTracks | None:
        """All-in-one track selection on a single screen.

        Shows three sections -- Video, Audio, Subtitles -- with Tab to
        navigate between them.  Video is single-select; Audio and
        Subtitles are multi-select.

        Returns a :class:`SelectedTracks` or ``None`` on cancel.
        """
        # -- Build labels and pre-selections --------------------------------
        if not bundle.video:
            self._console.print(
                "[bold red]Error:[/bold red] No video tracks available."
            )
            return None

        video_labels = [t.label for t in bundle.video]
        audio_labels = [t.label for t in bundle.audio]
        sub_labels = [t.label for t in bundle.subtitles]

        video_state = _ListState(items=video_labels)
        video_state.selected = {0}  # Default to first (best) quality.

        audio_state = _ListState(items=audio_labels)
        audio_pre = self._preselect_by_language(bundle.audio, preferred_audio)
        audio_state.selected = set(audio_pre)

        sub_state = _ListState(items=sub_labels)
        sub_pre = self._preselect_by_language(bundle.subtitles, preferred_subtitle)
        sub_state.selected = set(sub_pre)

        sections = _TrackSections(
            video=video_state,
            audio=audio_state,
            subtitles=sub_state,
        )

        page = self._page_size_tracks()

        try:
            while True:
                self._render_tracks(sections, bundle, page)
                key = _read_key()

                active = sections.active

                if key == KEY_TAB:
                    sections.next_section()
                elif key == KEY_SHIFT_TAB:
                    sections.prev_section()
                elif key == KEY_UP:
                    active.move_cursor(-1, page)
                elif key == KEY_DOWN:
                    active.move_cursor(1, page)
                elif key == KEY_PAGE_UP:
                    active.move_cursor(-page, page)
                elif key == KEY_PAGE_DOWN:
                    active.move_cursor(page, page)
                elif key == KEY_HOME:
                    active.move_cursor(-len(active.filtered_indices), page)
                elif key == KEY_END:
                    active.move_cursor(len(active.filtered_indices), page)
                elif key == KEY_SPACE:
                    if sections.active_section == 0:
                        # Video: single-select.
                        ri = active.cursor_real()
                        if ri is not None:
                            active.selected = {ri}
                    else:
                        active.toggle()
                elif key == KEY_A:
                    if sections.active_section != 0:
                        active.select_all()
                elif key == KEY_N:
                    if sections.active_section != 0:
                        active.deselect_all()
                elif key == KEY_ENTER:
                    self._clear()
                    return self._build_selected_tracks(sections, bundle)
                elif key in (KEY_ESC, KEY_Q):
                    self._clear()
                    return None
        except KeyboardInterrupt:
            self._clear()
            return None

    # =====================================================================
    # Rendering -- single / multi list
    # =====================================================================

    def _page_size(self) -> int:
        """Calculate how many items fit on screen for a list selector."""
        _, h = _term_size()
        # Reserve: title(2) + filter(1) + footer(3) + padding(4) + border(2)
        return max(3, h - 12)

    def _page_size_tracks(self) -> int:
        """Items per section in the track selector."""
        _, h = _term_size()
        # Three sections share vertical space; each needs header lines too.
        per_section = (h - 14) // 3
        return max(2, per_section)

    def _render_list(
        self,
        state: _ListState,
        title: str,
        page: int,
        *,
        multi: bool = False,
        badge: bool = False,
        show_count: bool = False,
    ) -> None:
        """Render a scrollable, filterable list inside a rich Panel."""
        w, _ = _term_size()
        lines: list[Text] = []

        # -- Filter bar -----------------------------------------------------
        if state.filter_text:
            ft = Text()
            ft.append("  / ", style="bold cyan")
            ft.append(state.filter_text, style="bold white")
            ft.append("_", style="blink bold cyan")
            ft.append(
                f"  ({state.visible_count} match{'es' if state.visible_count != 1 else ''})",
                style="dim",
            )
            lines.append(ft)
            lines.append(Text())

        visible = state.filtered_indices
        total = len(visible)

        # Ensure scroll offset is valid.
        state._fix_scroll(page)

        start = state.scroll_offset
        end = min(start + page, total)

        # -- Scroll-up indicator -------------------------------------------
        if start > 0:
            up_text = Text(f"  {_UP_ARROW} {start} more above", style="dim cyan")
            lines.append(up_text)

        # -- Items ---------------------------------------------------------
        for vi in range(start, end):
            real_idx = visible[vi]
            is_cursor = vi == state.cursor
            is_selected = real_idx in state.selected
            raw_label = state.items[real_idx]

            line = Text()

            # Cursor arrow
            if is_cursor:
                line.append(" > ", style="bold cyan")
            else:
                line.append("   ")

            # Checkbox / radio
            if multi:
                if is_selected:
                    line.append("[x]", style="bold cyan")
                else:
                    line.append("[ ]", style="dim")
            else:
                if is_selected or is_cursor:
                    line.append("(*)", style="bold cyan")
                else:
                    line.append("( )", style="dim")

            line.append(" ")

            # Number
            line.append(f"{real_idx + 1:>3}. ", style="dim")

            # Badge extraction
            if badge:
                label_text, badge_type = _extract_badge(raw_label)
                if badge_type and badge_type in _BADGE_STYLES:
                    style, badge_text = _BADGE_STYLES[badge_type]
                    line.append(badge_text, style=style)
                    line.append(" ")
                line.append(label_text, style="bold" if is_cursor else "")
            else:
                line.append(raw_label, style="bold" if is_cursor else "")

            lines.append(line)

        # -- Scroll-down indicator -----------------------------------------
        remaining_below = total - end
        if remaining_below > 0:
            dn_text = Text(
                f"  {_DOWN_ARROW} {remaining_below} more below",
                style="dim cyan",
            )
            lines.append(dn_text)

        # -- Footer --------------------------------------------------------
        lines.append(Text())

        if show_count and multi:
            count_line = Text()
            count_line.append(
                f"  {len(state.selected)} selected", style="bold cyan"
            )
            lines.append(count_line)

        footer = self._build_footer(multi)
        lines.append(footer)

        # -- Assemble panel ------------------------------------------------
        content = Text("\n").join(lines)

        panel = Panel(
            content,
            title=f"[bold]{title}[/bold]",
            border_style="cyan",
            padding=(1, 2),
            width=min(w, 100),
        )

        self._console.clear()
        self._console.print(panel)

    @staticmethod
    def _build_footer(multi: bool) -> Text:
        foot = Text("  ")
        if multi:
            foot.append("Space", style="bold")
            foot.append(" toggle  ", style="dim")
            foot.append("a", style="bold")
            foot.append(" all  ", style="dim")
            foot.append("n", style="bold")
            foot.append(" none  ", style="dim")
        foot.append("Enter", style="bold")
        foot.append(" confirm  ", style="dim")
        foot.append("Esc", style="bold")
        foot.append(" back  ", style="dim")
        foot.append("/", style="bold")
        foot.append(" filter", style="dim")
        return foot

    # =====================================================================
    # Rendering -- track selector
    # =====================================================================

    def _render_tracks(
        self,
        sections: _TrackSections,
        bundle: StreamBundle,
        page: int,
    ) -> None:
        """Render the all-in-one track selector."""
        w, _ = _term_size()
        lines: list[Text] = []

        section_defs: list[tuple[str, _ListState, bool, str | None]] = [
            ("VIDEO", sections.video, False, self._video_warning(bundle)),
            ("AUDIO", sections.audio, True, self._audio_warning(bundle)),
            ("SUBTITLES", sections.subtitles, True, self._subtitle_warning(bundle)),
        ]

        for idx, (label, st, multi, warning) in enumerate(section_defs):
            is_active = idx == sections.active_section

            # Section header
            header = Text()
            if is_active:
                header.append(f"  {_RIGHT_ARROW} ", style="bold cyan")
                header.append(label, style="bold cyan underline")
            else:
                header.append("    ", style="dim")
                header.append(label, style="dim bold")

            # Selected count
            if multi:
                count = len(st.selected)
                header.append(f"  ({count} selected)", style="dim cyan" if count else "dim")
            else:
                if st.selected:
                    sel_idx = min(st.selected)
                    if sel_idx < len(st.items):
                        header.append(f"  = {st.items[sel_idx]}", style="dim cyan")

            lines.append(header)

            # Warning messages
            if warning:
                warn_line = Text(f"    {warning}")
                lines.append(warn_line)

            # Items in this section
            visible = st.filtered_indices
            total = len(visible)

            if total == 0:
                empty_line = Text("      (none)", style="dim")
                lines.append(empty_line)
            else:
                st._fix_scroll(page)
                start = st.scroll_offset
                end = min(start + page, total)

                if start > 0:
                    lines.append(
                        Text(f"      {_UP_ARROW} {start} more", style="dim cyan")
                    )

                for vi in range(start, end):
                    real_idx = visible[vi]
                    is_cursor = is_active and vi == st.cursor
                    is_selected = real_idx in st.selected
                    raw_label = st.items[real_idx]

                    line = Text()
                    if is_cursor:
                        line.append("    > ", style="bold cyan")
                    else:
                        line.append("      ")

                    if multi:
                        if is_selected:
                            line.append("[x]", style="bold cyan")
                        else:
                            line.append("[ ]", style="dim")
                    else:
                        if is_selected:
                            line.append("(*)", style="bold cyan")
                        elif is_cursor:
                            line.append("( )", style="cyan")
                        else:
                            line.append("( )", style="dim")

                    line.append(" ")
                    line.append(
                        raw_label, style="bold" if is_cursor else ""
                    )
                    lines.append(line)

                remaining = total - end
                if remaining > 0:
                    lines.append(
                        Text(
                            f"      {_DOWN_ARROW} {remaining} more",
                            style="dim cyan",
                        )
                    )

            # Spacer between sections (except last).
            if idx < len(section_defs) - 1:
                lines.append(Text())

        # -- Summary panel -------------------------------------------------
        lines.append(Text())
        lines.append(Text("  " + _H_LINE * 40, style="dim"))
        lines.append(Text())

        summary = Text("  Selection: ", style="bold")
        # Video
        if sections.video.selected:
            v_idx = min(sections.video.selected)
            if v_idx < len(bundle.video):
                summary.append(bundle.video[v_idx].label, style="cyan")
        else:
            summary.append("(none)", style="dim red")

        summary.append("  |  ", style="dim")

        # Audio
        a_count = len(sections.audio.selected)
        if a_count:
            summary.append(f"{a_count} audio", style="cyan")
        else:
            summary.append("0 audio", style="dim")

        summary.append("  |  ", style="dim")

        # Subtitles
        s_count = len(sections.subtitles.selected)
        if s_count:
            summary.append(f"{s_count} subs", style="cyan")
        else:
            summary.append("0 subs", style="dim")

        lines.append(summary)

        # -- Footer --------------------------------------------------------
        lines.append(Text())
        foot = Text("  ")
        foot.append("Tab", style="bold")
        foot.append(" section  ", style="dim")
        foot.append("Space", style="bold")
        foot.append(" toggle  ", style="dim")
        foot.append("Enter", style="bold")
        foot.append(" confirm  ", style="dim")
        foot.append("Esc", style="bold")
        foot.append(" cancel", style="dim")
        lines.append(foot)

        content = Text("\n").join(lines)

        panel = Panel(
            content,
            title="[bold]Track Selection[/bold]",
            border_style="cyan",
            padding=(1, 2),
            width=min(w, 110),
        )

        self._console.clear()
        self._console.print(panel)

    # =====================================================================
    # Warnings
    # =====================================================================

    @staticmethod
    def _video_warning(bundle: StreamBundle) -> str | None:
        if not bundle.video:
            return "[bold red]ERROR: No video tracks available![/bold red]"
        return None

    @staticmethod
    def _audio_warning(bundle: StreamBundle) -> str | None:
        if not bundle.audio:
            return "[yellow]Warning: No audio tracks. Video will have no sound.[/yellow]"
        return None

    @staticmethod
    def _subtitle_warning(bundle: StreamBundle) -> str | None:
        if not bundle.subtitles:
            return "[dim]No subtitle tracks available.[/dim]"
        return None

    # =====================================================================
    # Result builders
    # =====================================================================

    @staticmethod
    def _build_selected_tracks(
        sections: _TrackSections, bundle: StreamBundle
    ) -> SelectedTracks:
        """Construct :class:`SelectedTracks` from the section states."""
        # Video (single-select, must have at least one)
        v_idx = min(sections.video.selected) if sections.video.selected else 0
        video = bundle.video[v_idx]

        audio = [bundle.audio[i] for i in sorted(sections.audio.selected)]
        subs = [bundle.subtitles[i] for i in sorted(sections.subtitles.selected)]

        return SelectedTracks(video=video, audio=audio, subtitles=subs)

    # =====================================================================
    # Helpers
    # =====================================================================

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

    def _clear(self) -> None:
        """Clear the selector display."""
        self._console.clear()


# ---------------------------------------------------------------------------
# Badge extraction
# ---------------------------------------------------------------------------

_BADGE_RE = re.compile(r"^\[(FILM|SERIE|ANIME)\]\s*", re.IGNORECASE)


def _extract_badge(text: str) -> tuple[str, str | None]:
    """Strip a ``[FILM]``/``[SERIE]``/``[ANIME]`` prefix from *text*.

    Returns ``(cleaned_text, badge_type_upper)`` or ``(text, None)`` if
    no badge is found.
    """
    m = _BADGE_RE.match(text)
    if m:
        return text[m.end() :], m.group(1).upper()
    return text, None


# ---------------------------------------------------------------------------
# Unicode glyphs (with ASCII fallback for Windows legacy consoles)
# ---------------------------------------------------------------------------

if platform.system() == "Windows":
    try:
        # Check if the console supports Unicode.
        "".encode(sys.stdout.encoding or "utf-8")
        _UP_ARROW = "\u25b2"
        _DOWN_ARROW = "\u25bc"
        _RIGHT_ARROW = "\u25b6"
        _H_LINE = "\u2500"
    except (UnicodeEncodeError, LookupError):
        _UP_ARROW = "^"
        _DOWN_ARROW = "v"
        _RIGHT_ARROW = ">"
        _H_LINE = "-"
else:
    _UP_ARROW = "\u25b2"
    _DOWN_ARROW = "\u25bc"
    _RIGHT_ARROW = "\u25b6"
    _H_LINE = "\u2500"
