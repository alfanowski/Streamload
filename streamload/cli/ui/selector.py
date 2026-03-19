"""Interactive terminal selector for the Streamload CLI.

Bulletproof FZF-style keyboard-driven selector with fuzzy filtering, scrollable
windows, multi-select, and an all-in-one track selection screen.

Key design decisions for macOS/Linux reliability:
- Uses ``tty.setcbreak()`` instead of ``tty.setraw()`` to preserve signal
  handling (Ctrl+C fires KeyboardInterrupt naturally).
- Uses ``os.read(fd, ...)`` for keypress reading instead of ``sys.stdin.read()``.
- Renders with ``sys.stdout.write()`` + ANSI escape codes instead of Rich
  ``Console.clear()`` / ``Console.print()`` to avoid conflicts with cbreak mode.
- Single try/finally block wraps ALL terminal manipulation.

Exports :class:`InteractiveSelector` with three public methods:

- ``select_from_list``  -- single-select with fuzzy filter
- ``select_episodes``   -- multi-select with range support
- ``select_tracks``     -- unified video/audio/subtitle picker
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import sys
from dataclasses import dataclass, field
from typing import Sequence

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

KEY_Q = "q"
KEY_A = "a"
KEY_N = "n"

# ---------------------------------------------------------------------------
# ANSI escape helpers
# ---------------------------------------------------------------------------

_IS_WINDOWS = platform.system() == "Windows"

# Escape sequences for terminal control
ESC = "\033"
CLEAR_SCREEN = f"{ESC}[2J{ESC}[H"
HIDE_CURSOR = f"{ESC}[?25l"
SHOW_CURSOR = f"{ESC}[?25h"

# ANSI color/style codes
RESET = f"{ESC}[0m"
BOLD = f"{ESC}[1m"
DIM = f"{ESC}[2m"
UNDERLINE = f"{ESC}[4m"
BLINK = f"{ESC}[5m"

FG_RED = f"{ESC}[31m"
FG_GREEN = f"{ESC}[32m"
FG_YELLOW = f"{ESC}[33m"
FG_BLUE = f"{ESC}[34m"
FG_MAGENTA = f"{ESC}[35m"
FG_CYAN = f"{ESC}[36m"
FG_WHITE = f"{ESC}[37m"
FG_BRIGHT_WHITE = f"{ESC}[97m"

BG_BLUE = f"{ESC}[44m"
BG_MAGENTA = f"{ESC}[45m"
BG_RED = f"{ESC}[41m"
BG_CYAN = f"{ESC}[46m"

# ---------------------------------------------------------------------------
# Eye-catching ASCII banner
# ---------------------------------------------------------------------------

BANNER_LINES = [
    "███████╗████████╗██████╗ ███████╗ █████╗ ███╗   ███╗██╗      ██████╗  █████╗ ██████╗ ",
    "██╔════╝╚══██╔══╝██╔══██╗██╔════╝██╔══██╗████╗ ████║██║     ██╔═══██╗██╔══██╗██╔══██╗",
    "███████╗   ██║   ██████╔╝█████╗  ███████║██╔████╔██║██║     ██║   ██║███████║██║  ██║",
    "╚════██║   ██║   ██╔══██╗██╔══╝  ██╔══██║██║╚██╔╝██║██║     ██║   ██║██╔══██║██║  ██║",
    "███████║   ██║   ██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗╚██████╔╝██║  ██║██████╔╝",
    "╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝ ",
]

BANNER_COMPACT_LINES = [
    "╔═╗╔╦╗╦═╗╔═╗╔═╗╔╦╗╦  ╔═╗╔═╗╔╦╗",
    "╚═╗ ║ ╠╦╝║╣ ╠═╣║║║║  ║ ║╠═╣ ║║",
    "╚═╝ ╩ ╩╚═╚═╝╩ ╩╩ ╩╩═╝╚═╝╩ ╩═╩╝",
]


def _build_banner(width: int, version: str = "") -> str:
    """Build a centered, boxed banner that adapts to terminal width."""
    # Pick banner variant based on width
    lines = BANNER_LINES if width >= 90 else BANNER_COMPACT_LINES
    max_line_len = max(len(l) for l in lines)

    # If terminal is too narrow even for compact, skip banner
    if width < 38:
        return f"{BOLD}{FG_CYAN}  STREAMLOAD{RESET}"

    # Box width
    box_w = min(width - 2, max_line_len + 6)

    out = []
    # Top border
    out.append(f"{FG_CYAN}{'─' * box_w}{RESET}")

    # Banner lines centered
    for line in lines:
        padding = (box_w - len(line)) // 2
        out.append(f"{BOLD}{FG_CYAN}{' ' * max(padding, 1)}{line}{RESET}")

    # Version line centered
    if version:
        ver_text = f"v{version}  │  Professional Media Downloader"
    else:
        ver_text = "Professional Media Downloader"
    ver_pad = (box_w - len(ver_text)) // 2
    out.append(f"{DIM}{' ' * max(ver_pad, 1)}{ver_text}{RESET}")

    # Bottom border
    out.append(f"{FG_CYAN}{'─' * box_w}{RESET}")

    return "\n".join(out)

# Unicode glyphs
UP_ARROW = "\u25b2"
DOWN_ARROW = "\u25bc"
RIGHT_ARROW = "\u25b6"
H_LINE = "\u2500"
DOT = "\u2022"

# Badge styles for media types (bg_color, fg_color)
_BADGE_COLORS: dict[str, tuple[str, str]] = {
    "FILM": (BG_BLUE, FG_BRIGHT_WHITE),
    "SERIE": (BG_MAGENTA, FG_BRIGHT_WHITE),
    "ANIME": (BG_RED, FG_BRIGHT_WHITE),
}

# ---------------------------------------------------------------------------
# Cross-platform raw key reading
# ---------------------------------------------------------------------------


def _read_key_unix(fd: int) -> str:
    """Read a single keypress on Unix using cbreak mode and os.read.

    The terminal must already be in cbreak mode (done by the caller).
    Uses ``os.read(fd, 1)`` for the first byte, then ``os.read(fd, 10)``
    to slurp any remaining escape sequence bytes in a non-blocking fashion.
    """
    try:
        data = os.read(fd, 1)
    except (OSError, IOError):
        return ""

    if not data:
        return ""

    ch = data[0]

    # ESC byte -> possible escape sequence
    if ch == 0x1B:
        import select as _sel

        # Check if more bytes are immediately available
        ready, _, _ = _sel.select([fd], [], [], 0.05)
        if not ready:
            return KEY_ESC

        # Read rest of the escape sequence (up to 10 bytes, non-blocking)
        try:
            rest = os.read(fd, 10)
        except (OSError, IOError):
            return KEY_ESC

        if not rest:
            return KEY_ESC

        seq = rest.decode("utf-8", errors="replace")

        # CSI sequences: ESC [ ...
        if seq.startswith("["):
            seq = seq[1:]  # strip the '['

            if seq == "A":
                return KEY_UP
            if seq == "B":
                return KEY_DOWN
            if seq == "C":
                return "right"
            if seq == "D":
                return "left"
            if seq == "H":
                return KEY_HOME
            if seq == "F":
                return KEY_END
            if seq == "Z":
                return KEY_SHIFT_TAB

            # Extended: ESC [ <number> ~
            if len(seq) == 2 and seq[1] == "~":
                return {
                    "1": KEY_HOME,
                    "2": "insert",
                    "3": "delete",
                    "4": KEY_END,
                    "5": KEY_PAGE_UP,
                    "6": KEY_PAGE_DOWN,
                }.get(seq[0], "")

            # Longer extended sequences (e.g., ESC [ 1 ; 2 A for shift+arrow)
            # Just consume and ignore
            return ""

        # SS3 sequences: ESC O ...
        if seq.startswith("O"):
            code = seq[1:2]
            if code == "H":
                return KEY_HOME
            if code == "F":
                return KEY_END
            if code == "Z":
                return KEY_SHIFT_TAB
            return ""

        return KEY_ESC

    # Normal single-byte characters
    if ch in (0x0D, 0x0A):
        return KEY_ENTER
    if ch == 0x20:
        return KEY_SPACE
    if ch == 0x09:
        return KEY_TAB
    if ch in (0x7F, 0x08):
        return KEY_BACKSPACE
    if ch == 0x03:
        raise KeyboardInterrupt
    if ch == 0x04:  # Ctrl+D
        raise KeyboardInterrupt
    # Ignore other control characters
    if ch < 32:
        return ""

    return chr(ch)


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
    """Return True if every character of *query* appears in *text* in order."""
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
# Badge extraction
# ---------------------------------------------------------------------------

_BADGE_RE = re.compile(r"^\[(FILM|SERIE|ANIME)\]\s*", re.IGNORECASE)


def _extract_badge(text: str) -> tuple[str, str | None]:
    """Strip a ``[FILM]``/``[SERIE]``/``[ANIME]`` prefix from *text*.

    Returns ``(cleaned_text, badge_type_upper)`` or ``(text, None)``.
    """
    m = _BADGE_RE.match(text)
    if m:
        return text[m.end():], m.group(1).upper()
    return text, None


# ---------------------------------------------------------------------------
# Terminal size
# ---------------------------------------------------------------------------

_MIN_WIDTH = 60
_MIN_HEIGHT = 16


def _term_size() -> tuple[int, int]:
    """Return (columns, lines) clamped to minimums."""
    sz = shutil.get_terminal_size((80, 24))
    return max(sz.columns, _MIN_WIDTH), max(sz.lines, _MIN_HEIGHT)


# ---------------------------------------------------------------------------
# Rendering helper: build strings with ANSI codes
# ---------------------------------------------------------------------------


def _truncate(text: str, max_width: int) -> str:
    """Truncate text to max_width, adding ellipsis if needed.

    Only counts visible characters (strips ANSI codes for length calculation).
    """
    # For simplicity, we do raw truncation. ANSI codes inside text might
    # get cut, but we always append RESET after rendering lines, so the
    # terminal will not be left in a bad state.
    visible_len = len(_strip_ansi(text))
    if visible_len <= max_width:
        return text
    # Rough truncation -- find the point where visible chars hit limit
    count = 0
    i = 0
    while i < len(text) and count < max_width - 1:
        if text[i] == "\033":
            # Skip entire escape sequence
            while i < len(text) and text[i] != "m":
                i += 1
            i += 1  # skip the 'm'
            continue
        count += 1
        i += 1
    return text[:i] + "\u2026" + RESET


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return _ANSI_RE.sub("", text)


def _pad_line(text: str, width: int) -> str:
    """Pad a line (containing ANSI codes) to fill `width` visible characters."""
    visible_len = len(_strip_ansi(text))
    if visible_len < width:
        return text + " " * (width - visible_len)
    return text


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
        return self.filtered_indices[filtered_pos]

    def cursor_real(self) -> int | None:
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
    active_section: int = 0

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

    * **Up / Down**    -- move cursor
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

    def __init__(self, console: object = None) -> None:
        # We accept a Console for API compatibility but do NOT use it
        # for rendering during interactive loops.
        self._console = console
        self._header_text: str | None = None
        self._version: str = ""

    def set_header(self, header: str) -> None:
        """Set a persistent header shown above every screen.

        Note: the header is stored but we use our own banner for rendering
        during interactive loops (the Rich markup in header cannot be
        rendered through raw ANSI writes).
        """
        self._header_text = header

    # =====================================================================
    # Terminal context manager
    # =====================================================================

    def _enter_interactive(self) -> tuple[int, object | None]:
        """Set up terminal for interactive input.

        Returns (fd, old_settings) on Unix, (-1, None) on Windows.
        The caller MUST call _exit_interactive in a finally block.
        """
        if _IS_WINDOWS:
            sys.stdout.write(HIDE_CURSOR)
            sys.stdout.flush()
            return -1, None

        import termios
        import tty

        fd = sys.stdin.fileno()
        old = None
        try:
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except (termios.error, OSError, AttributeError) as exc:
            # If we can't set cbreak, try setraw as last resort
            if old is not None:
                try:
                    tty.setraw(fd)
                except Exception:
                    pass

        sys.stdout.write(HIDE_CURSOR)
        sys.stdout.flush()
        return fd, old

    def _exit_interactive(self, fd: int, old_settings: object | None) -> None:
        """Restore terminal state. MUST be called in a finally block."""
        try:
            sys.stdout.write(SHOW_CURSOR + CLEAR_SCREEN)
            sys.stdout.flush()
        except (OSError, IOError):
            pass

        if old_settings is not None and not _IS_WINDOWS:
            import termios
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except (termios.error, OSError):
                pass

    def _read_key(self, fd: int) -> str:
        """Read a single keypress."""
        if _IS_WINDOWS:
            return _read_key_windows()
        return _read_key_unix(fd)

    # =====================================================================
    # Rendering engine (pure ANSI, no Rich)
    # =====================================================================

    def _write_screen(self, lines: list[str]) -> None:
        """Clear screen and write all lines at once via sys.stdout."""
        w, h = _term_size()
        output = CLEAR_SCREEN

        for line in lines:
            output += _truncate(line, w - 1) + RESET + "\n"

        try:
            sys.stdout.write(output)
            sys.stdout.flush()
        except (OSError, IOError):
            pass

    def _get_banner_lines(self) -> list[str]:
        """Return the banner as a list of strings to display."""
        w, _ = _term_size()
        return _build_banner(w, self._version).split("\n")

    def set_version(self, version: str) -> None:
        """Set version string for the banner."""
        self._version = version

    def _get_version_line(self) -> str:
        """Extract version from stored header if available."""
        if self._header_text:
            # Try to find version pattern in header
            m = re.search(r"v([\d.]+)", self._header_text)
            if m:
                return (
                    f"  {BOLD}{FG_WHITE}v{m.group(1)}{RESET}"
                    f"  {DIM}|  Professional media downloader{RESET}"
                )
        return ""

    # =====================================================================
    # Box drawing helpers
    # =====================================================================

    def _draw_box_top(self, title: str, width: int) -> str:
        """Draw the top border of a box with title."""
        title_clean = f" {title} "
        inner = width - 2
        title_len = len(title_clean)
        left = (inner - title_len) // 2
        right = inner - title_len - left
        return (
            f"{FG_CYAN}{BOLD}"
            f"\u256d{H_LINE * left}{RESET}{BOLD}{FG_WHITE}{title_clean}"
            f"{FG_CYAN}{BOLD}{H_LINE * right}\u256e{RESET}"
        )

    def _draw_box_bottom(self, width: int) -> str:
        """Draw the bottom border of a box."""
        inner = width - 2
        return f"{FG_CYAN}{BOLD}\u2570{H_LINE * inner}\u256f{RESET}"

    def _draw_box_line(self, content: str, width: int) -> str:
        """Draw a line inside a box with side borders."""
        inner = width - 4  # 2 for borders + 2 for padding
        padded = _pad_line(f" {content}", inner + 1)
        return f"{FG_CYAN}\u2502{RESET} {padded}{FG_CYAN}\u2502{RESET}"

    def _draw_box_empty(self, width: int) -> str:
        """Draw an empty line inside a box."""
        inner = width - 2
        return f"{FG_CYAN}\u2502{RESET}{' ' * inner}{FG_CYAN}\u2502{RESET}"

    def _draw_box_separator(self, width: int) -> str:
        """Draw a horizontal separator inside a box."""
        inner = width - 2
        return f"{FG_CYAN}\u251c{H_LINE * inner}\u2524{RESET}"

    # =====================================================================
    # Page size calculations
    # =====================================================================

    def _page_size(self) -> int:
        _, h = _term_size()
        # Reserve: banner(8) + title(2) + filter(2) + footer(3) + border(4) + padding(3)
        overhead = 20
        return max(3, h - overhead)

    def _page_size_tracks(self) -> int:
        _, h = _term_size()
        per_section = (h - 22) // 3
        return max(2, per_section)

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

        Returns the selected index, or ``None`` if cancelled.
        """
        if not items:
            return None

        state = _ListState(items=list(items))
        page = self._page_size()

        fd, old = self._enter_interactive()
        try:
            while True:
                self._render_list(state, title, page, multi=False, badge=show_type_badge)
                key = self._read_key(fd)

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
                    return state.cursor_real()
                elif key == KEY_ESC:
                    if state.filter_text:
                        state.filter_text = ""
                        state.refilter()
                    else:
                        return None
                elif key == KEY_BACKSPACE:
                    if state.filter_text:
                        state.filter_text = state.filter_text[:-1]
                        state.refilter()
                elif key == KEY_Q and not state.filter_text:
                    return None
                elif len(key) == 1 and key.isprintable():
                    state.filter_text += key
                    state.refilter()
        except (KeyboardInterrupt, EOFError):
            return None
        except Exception:
            return None
        finally:
            self._exit_interactive(fd, old)

    def select_episodes(
        self,
        episodes: list[Episode],
        title: str = "",
    ) -> list[Episode] | None:
        """Multi-select episodes with fuzzy filter and range support.

        Returns a list of selected :class:`Episode` objects or ``None``.
        """
        if not episodes:
            return None

        labels = [f"E{ep.number:02d}  {ep.title}" for ep in episodes]
        state = _ListState(items=labels)
        page = self._page_size()

        fd, old = self._enter_interactive()
        try:
            while True:
                self._render_list(
                    state,
                    title or "Select episodes",
                    page,
                    multi=True,
                    show_count=True,
                )
                key = self._read_key(fd)

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
                    if not state.selected:
                        return None
                    indices = sorted(state.selected)
                    return [episodes[i] for i in indices]
                elif key == KEY_ESC:
                    if state.filter_text:
                        state.filter_text = ""
                        state.refilter()
                    else:
                        return None
                elif key == KEY_BACKSPACE:
                    if state.filter_text:
                        state.filter_text = state.filter_text[:-1]
                        state.refilter()
                elif key == KEY_Q and not state.filter_text:
                    return None
                elif len(key) == 1 and key.isprintable():
                    state.filter_text += key
                    state.refilter()
                    if _RANGE_RE.match(state.filter_text):
                        parsed = _parse_ranges(state.filter_text, len(episodes))
                        if parsed is not None:
                            state.selected = set(parsed)
        except (KeyboardInterrupt, EOFError):
            return None
        except Exception:
            return None
        finally:
            self._exit_interactive(fd, old)

    def select_tracks(
        self,
        bundle: StreamBundle,
        preferred_audio: str = "",
        preferred_subtitle: str = "",
    ) -> SelectedTracks | None:
        """All-in-one track selection.

        Shows three sections -- Video, Audio, Subtitles -- with Tab to
        navigate between them.  Returns :class:`SelectedTracks` or ``None``.
        """
        if not bundle.video:
            return None

        video_labels = [t.label for t in bundle.video]
        audio_labels = [t.label for t in bundle.audio]
        sub_labels = [t.label for t in bundle.subtitles]

        video_state = _ListState(items=video_labels)
        video_state.selected = {0}

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

        fd, old = self._enter_interactive()
        try:
            while True:
                self._render_tracks(sections, bundle, page)
                key = self._read_key(fd)

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
                    return self._build_selected_tracks(sections, bundle)
                elif key in (KEY_ESC, KEY_Q):
                    return None
        except (KeyboardInterrupt, EOFError):
            return None
        except Exception:
            return None
        finally:
            self._exit_interactive(fd, old)

    # =====================================================================
    # Rendering -- single / multi list
    # =====================================================================

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
        """Render a scrollable, filterable list with ANSI codes."""
        w, _ = _term_size()
        box_width = min(w, 100)
        out: list[str] = []

        # -- Banner --
        for bline in self._get_banner_lines():
            out.append(bline)
        vline = self._get_version_line()
        if vline:
            out.append(vline)
        out.append("")

        # -- Box top --
        out.append(self._draw_box_top(title, box_width))
        out.append(self._draw_box_empty(box_width))

        # -- Filter bar --
        if state.filter_text:
            match_word = "matches" if state.visible_count != 1 else "match"
            filter_line = (
                f"  {BOLD}{FG_CYAN}/{RESET} "
                f"{BOLD}{FG_WHITE}{state.filter_text}{RESET}"
                f"{BLINK}{BOLD}{FG_CYAN}_{RESET}"
                f"  {DIM}({state.visible_count} {match_word}){RESET}"
            )
            out.append(self._draw_box_line(filter_line, box_width))
            out.append(self._draw_box_empty(box_width))

        visible = state.filtered_indices
        total = len(visible)

        state._fix_scroll(page)
        start = state.scroll_offset
        end = min(start + page, total)

        # -- Scroll up indicator --
        if start > 0:
            up_line = f"  {DIM}{FG_CYAN}{UP_ARROW} {start} more above{RESET}"
            out.append(self._draw_box_line(up_line, box_width))

        # -- Items --
        for vi in range(start, end):
            real_idx = visible[vi]
            is_cursor = vi == state.cursor
            is_selected = real_idx in state.selected
            raw_label = state.items[real_idx]

            line = ""

            # Cursor arrow
            if is_cursor:
                line += f" {BOLD}{FG_CYAN}>{RESET} "
            else:
                line += "   "

            # Checkbox / radio
            if multi:
                if is_selected:
                    line += f"{BOLD}{FG_CYAN}[x]{RESET}"
                else:
                    line += f"{DIM}[ ]{RESET}"
            else:
                if is_selected or is_cursor:
                    line += f"{BOLD}{FG_CYAN}(*){RESET}"
                else:
                    line += f"{DIM}( ){RESET}"

            line += " "

            # Number
            line += f"{DIM}{real_idx + 1:>3}. {RESET}"

            # Badge extraction
            if badge:
                label_text, badge_type = _extract_badge(raw_label)
                if badge_type and badge_type in _BADGE_COLORS:
                    bg, fg = _BADGE_COLORS[badge_type]
                    line += f"{bg}{fg}{BOLD} {badge_type} {RESET} "
                style = f"{BOLD}{FG_WHITE}" if is_cursor else ""
                line += f"{style}{label_text}{RESET}"
            else:
                style = f"{BOLD}{FG_WHITE}" if is_cursor else ""
                line += f"{style}{raw_label}{RESET}"

            out.append(self._draw_box_line(line, box_width))

        # -- No results --
        if total == 0:
            no_results = f"  {DIM}No matches found{RESET}"
            out.append(self._draw_box_line(no_results, box_width))

        # -- Scroll down indicator --
        remaining_below = total - end
        if remaining_below > 0:
            dn_line = f"  {DIM}{FG_CYAN}{DOWN_ARROW} {remaining_below} more below{RESET}"
            out.append(self._draw_box_line(dn_line, box_width))

        out.append(self._draw_box_empty(box_width))

        # -- Selected count --
        if show_count and multi:
            count_line = f"  {BOLD}{FG_CYAN}{len(state.selected)} selected{RESET}"
            out.append(self._draw_box_line(count_line, box_width))

        # -- Footer --
        footer = self._build_footer_str(multi)
        out.append(self._draw_box_line(footer, box_width))
        out.append(self._draw_box_empty(box_width))

        # -- Box bottom --
        out.append(self._draw_box_bottom(box_width))

        self._write_screen(out)

    @staticmethod
    def _build_footer_str(multi: bool) -> str:
        foot = "  "
        if multi:
            foot += f"{BOLD}Space{RESET}{DIM} toggle  {RESET}"
            foot += f"{BOLD}a{RESET}{DIM} all  {RESET}"
            foot += f"{BOLD}n{RESET}{DIM} none  {RESET}"
        foot += f"{BOLD}Enter{RESET}{DIM} confirm  {RESET}"
        foot += f"{BOLD}Esc{RESET}{DIM} back  {RESET}"
        foot += f"{BOLD}/{RESET}{DIM} filter{RESET}"
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
        """Render the all-in-one track selector with ANSI codes."""
        w, _ = _term_size()
        box_width = min(w, 110)
        out: list[str] = []

        # -- Banner --
        for bline in self._get_banner_lines():
            out.append(bline)
        vline = self._get_version_line()
        if vline:
            out.append(vline)
        out.append("")

        # -- Box top --
        out.append(self._draw_box_top("Track Selection", box_width))
        out.append(self._draw_box_empty(box_width))

        section_defs: list[tuple[str, _ListState, bool, str | None]] = [
            ("VIDEO", sections.video, False, self._video_warning(bundle)),
            ("AUDIO", sections.audio, True, self._audio_warning(bundle)),
            ("SUBTITLES", sections.subtitles, True, self._subtitle_warning(bundle)),
        ]

        for idx, (label, st, multi, warning) in enumerate(section_defs):
            is_active = idx == sections.active_section

            # Section header
            if is_active:
                header = (
                    f"  {BOLD}{FG_CYAN}{RIGHT_ARROW} {UNDERLINE}{label}{RESET}"
                )
            else:
                header = f"    {DIM}{BOLD}{label}{RESET}"

            # Selected count/info
            if multi:
                count = len(st.selected)
                if count:
                    header += f"  {DIM}{FG_CYAN}({count} selected){RESET}"
                else:
                    header += f"  {DIM}(0 selected){RESET}"
            else:
                if st.selected:
                    sel_idx = min(st.selected)
                    if sel_idx < len(st.items):
                        header += f"  {DIM}{FG_CYAN}= {st.items[sel_idx]}{RESET}"

            out.append(self._draw_box_line(header, box_width))

            # Warning
            if warning:
                out.append(self._draw_box_line(f"    {FG_YELLOW}{warning}{RESET}", box_width))

            # Items
            visible = st.filtered_indices
            total = len(visible)

            if total == 0:
                out.append(self._draw_box_line(f"      {DIM}(none){RESET}", box_width))
            else:
                st._fix_scroll(page)
                start = st.scroll_offset
                end = min(start + page, total)

                if start > 0:
                    out.append(self._draw_box_line(
                        f"      {DIM}{FG_CYAN}{UP_ARROW} {start} more{RESET}", box_width
                    ))

                for vi in range(start, end):
                    real_idx = visible[vi]
                    is_cursor = is_active and vi == st.cursor
                    is_selected = real_idx in st.selected
                    raw_label = st.items[real_idx]

                    line = ""
                    if is_cursor:
                        line += f"    {BOLD}{FG_CYAN}> {RESET}"
                    else:
                        line += "      "

                    if multi:
                        if is_selected:
                            line += f"{BOLD}{FG_CYAN}[x]{RESET}"
                        else:
                            line += f"{DIM}[ ]{RESET}"
                    else:
                        if is_selected:
                            line += f"{BOLD}{FG_CYAN}(*){RESET}"
                        elif is_cursor:
                            line += f"{FG_CYAN}( ){RESET}"
                        else:
                            line += f"{DIM}( ){RESET}"

                    line += " "
                    style = f"{BOLD}" if is_cursor else ""
                    line += f"{style}{raw_label}{RESET}"

                    out.append(self._draw_box_line(line, box_width))

                remaining = total - end
                if remaining > 0:
                    out.append(self._draw_box_line(
                        f"      {DIM}{FG_CYAN}{DOWN_ARROW} {remaining} more{RESET}", box_width
                    ))

            # Spacer between sections
            if idx < len(section_defs) - 1:
                out.append(self._draw_box_empty(box_width))

        # -- Summary --
        out.append(self._draw_box_empty(box_width))
        out.append(self._draw_box_line(
            f"  {DIM}{FG_CYAN}{H_LINE * 40}{RESET}", box_width
        ))
        out.append(self._draw_box_empty(box_width))

        summary = f"  {BOLD}Selection:{RESET} "

        # Video
        if sections.video.selected:
            v_idx = min(sections.video.selected)
            if v_idx < len(bundle.video):
                summary += f"{FG_CYAN}{bundle.video[v_idx].label}{RESET}"
        else:
            summary += f"{DIM}{FG_RED}(none){RESET}"

        summary += f"  {DIM}|{RESET}  "

        # Audio
        a_count = len(sections.audio.selected)
        if a_count:
            summary += f"{FG_CYAN}{a_count} audio{RESET}"
        else:
            summary += f"{DIM}0 audio{RESET}"

        summary += f"  {DIM}|{RESET}  "

        # Subtitles
        s_count = len(sections.subtitles.selected)
        if s_count:
            summary += f"{FG_CYAN}{s_count} subs{RESET}"
        else:
            summary += f"{DIM}0 subs{RESET}"

        out.append(self._draw_box_line(summary, box_width))

        # -- Footer --
        out.append(self._draw_box_empty(box_width))
        foot = (
            f"  {BOLD}Tab{RESET}{DIM} section  {RESET}"
            f"{BOLD}Space{RESET}{DIM} toggle  {RESET}"
            f"{BOLD}Enter{RESET}{DIM} confirm  {RESET}"
            f"{BOLD}Esc{RESET}{DIM} cancel{RESET}"
        )
        out.append(self._draw_box_line(foot, box_width))
        out.append(self._draw_box_empty(box_width))

        # -- Box bottom --
        out.append(self._draw_box_bottom(box_width))

        self._write_screen(out)

    # =====================================================================
    # Warnings
    # =====================================================================

    @staticmethod
    def _video_warning(bundle: StreamBundle) -> str | None:
        if not bundle.video:
            return "ERROR: No video tracks available!"
        return None

    @staticmethod
    def _audio_warning(bundle: StreamBundle) -> str | None:
        if not bundle.audio:
            return "Warning: No audio tracks. Video will have no sound."
        return None

    @staticmethod
    def _subtitle_warning(bundle: StreamBundle) -> str | None:
        if not bundle.subtitles:
            return "No subtitle tracks available."
        return None

    # =====================================================================
    # Result builders
    # =====================================================================

    @staticmethod
    def _build_selected_tracks(
        sections: _TrackSections, bundle: StreamBundle
    ) -> SelectedTracks:
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
