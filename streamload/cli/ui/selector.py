"""Interactive terminal selector for the Streamload CLI.

Uses Python's built-in ``curses`` module for both input handling and rendering.
This is the industry-standard approach for terminal UIs on Unix (macOS/Linux)
and avoids all issues with termios/cbreak, Rich markup leaking, and arrow key
handling.

On Windows (where curses is not available), falls back to msvcrt for input
and ANSI escape codes for rendering.

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
import threading
import time
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
# Platform detection
# ---------------------------------------------------------------------------

_IS_WINDOWS = platform.system() == "Windows"

# ---------------------------------------------------------------------------
# Rich markup stripping
# ---------------------------------------------------------------------------

# Known Rich style keywords that appear as the first word in a tag.
# This ensures we only strip genuine Rich markup, not literal content
# like "[forced]" or "[FILM]".
_RICH_STYLES = (
    "bold",
    "dim",
    "italic",
    "underline",
    "blink",
    "reverse",
    "strike",
    "white",
    "black",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "bright_white",
    "bright_black",
    "bright_red",
    "bright_green",
    "bright_yellow",
    "bright_blue",
    "bright_magenta",
    "bright_cyan",
    "on",
    "not",
    "link",
)

# Matches Rich-style tags: [bold], [/bold], [bold white on blue], [/dim], etc.
# The first word after [/ must be a known Rich style keyword.
_RICH_TAG_RE = re.compile(
    r"\[/?"
    r"(?:" + "|".join(re.escape(s) for s in _RICH_STYLES) + r")"
    r"(?:\s+[a-zA-Z0-9_# ]+)*"
    r"\]"
)


def _strip_rich_markup(text: str) -> str:
    """Remove Rich markup tags like [bold], [/dim], [bold white on blue] etc.

    Only strips tags that start with a known Rich style keyword.
    Preserves literal content like [forced] or [FILM].

    Returns plain text with Rich-style tags removed.
    """
    return _RICH_TAG_RE.sub("", text)


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

BANNER_LINES_COMPACT = [
    " ╔═╗╔╦╗╦═╗╔═╗╔═╗╔╦╗╦  ╔═╗╔═╗╔╦╗",
    " ╚═╗ ║ ╠╦╝║╣ ╠═╣║║║║  ║ ║╠═╣ ║║",
    " ╚═╝ ╩ ╩╚═╚═╝╩ ╩╩ ╩╩═╝╚═╝╩ ╩═╩╝",
]

BANNER_LINES_LARGE = [
    " ███████╗████████╗██████╗ ███████╗ █████╗ ███╗   ███╗██╗      ██████╗  █████╗ ██████╗ ",
    " ██╔════╝╚══██╔══╝██╔══██╗██╔════╝██╔══██╗████╗ ████║██║     ██╔═══██╗██╔══██╗██╔══██╗",
    " ███████╗   ██║   ██████╔╝█████╗  ███████║██╔████╔██║██║     ██║   ██║███████║██║  ██║",
    " ╚════██║   ██║   ██╔══██╗██╔══╝  ██╔══██║██║╚██╔╝██║██║     ██║   ██║██╔══██║██║  ██║",
    " ███████║   ██║   ██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗╚██████╔╝██║  ██║██████╔╝",
    " ╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝ ",
]

BANNER_LINES = BANNER_LINES_COMPACT  # default for compatibility
BANNER_WIDTH = max(len(line) for line in BANNER_LINES_COMPACT)  # 34
BANNER_LARGE_WIDTH = max(len(line) for line in BANNER_LINES_LARGE)  # ~89

# Unicode glyphs
UP_ARROW = "\u25b2"
DOWN_ARROW = "\u25bc"
RIGHT_ARROW = "\u25b6"
H_LINE = "\u2500"
DOT = "\u2022"

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
# Badge extraction from item strings
# ---------------------------------------------------------------------------

_BADGE_RE = re.compile(r"^\[(FILM|SERIE|ANIME)\]\s*", re.IGNORECASE)
# After Rich markup stripping, "[bold white on blue] FILM [/bold white on blue]"
# becomes " FILM ". This pattern catches that (uppercase only to avoid false
# positives on normal title text):
_BADGE_STRIPPED_RE = re.compile(r"^\s*(FILM|SERIE|ANIME)\s{2,}")


def _extract_badge(text: str) -> tuple[str, str | None]:
    """Extract a FILM/SERIE/ANIME badge from the start of *text*.

    Handles two formats:
    - Literal bracket prefix: ``[FILM] Cars ...``
    - Stripped Rich markup result: `` FILM  Cars ...``

    Returns ``(cleaned_text, badge_type_upper)`` or ``(text, None)``.
    """
    # Try bracket format first: [FILM] ...
    m = _BADGE_RE.match(text)
    if m:
        return text[m.end() :], m.group(1).upper()
    # Try stripped Rich format: " FILM  ..."
    m = _BADGE_STRIPPED_RE.match(text)
    if m:
        return text[m.end() :].lstrip(), m.group(1).upper()
    return text, None


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
# Windows fallback: msvcrt key reading + ANSI rendering
# ---------------------------------------------------------------------------


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
# ANSI escape codes for Windows fallback rendering
# ---------------------------------------------------------------------------

_ESC = "\033"
_CLEAR_SCREEN = f"{_ESC}[2J{_ESC}[H"
_HIDE_CURSOR = f"{_ESC}[?25l"
_SHOW_CURSOR = f"{_ESC}[?25h"
_RESET = f"{_ESC}[0m"
_BOLD = f"{_ESC}[1m"
_DIM = f"{_ESC}[2m"
_FG_CYAN = f"{_ESC}[36m"
_FG_WHITE = f"{_ESC}[37m"
_FG_YELLOW = f"{_ESC}[33m"
_FG_RED = f"{_ESC}[31m"
_BG_BLUE = f"{_ESC}[44m"
_BG_MAGENTA = f"{_ESC}[45m"
_BG_RED = f"{_ESC}[41m"
_FG_BRIGHT_WHITE = f"{_ESC}[97m"


# ---------------------------------------------------------------------------
# Curses color pair IDs
# ---------------------------------------------------------------------------

# We define these as constants so curses.init_pair() and curses.color_pair()
# use consistent IDs.
_CP_CYAN = 1  # cyan on default bg
_CP_WHITE = 2  # white on default bg
_CP_DIM = 3  # dim (white on default, rendered with A_DIM)
_CP_BADGE_FILM = 4  # white on blue
_CP_BADGE_SERIE = 5  # white on magenta
_CP_BADGE_ANIME = 6  # white on red
_CP_YELLOW = 7  # yellow on default bg
_CP_RED = 8  # red on default bg
_CP_GREEN = 9  # green on default bg


# ---------------------------------------------------------------------------
# InteractiveSelector
# ---------------------------------------------------------------------------


class InteractiveSelector:
    """Curses-based interactive selector for the Streamload CLI.

    Uses Python's built-in ``curses`` module for both keyboard input and
    screen rendering. This approach is battle-tested on macOS Terminal,
    iTerm2, and all standard Linux terminals.

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

    def __init__(self, console: object = None, i18n: object = None) -> None:
        self._console = console
        self._i18n = i18n
        self._header_text: str | None = None
        self._version: str = ""
        # curses screen object (set during interactive sessions on Unix)
        self._stdscr: object | None = None
        self._has_colors: bool = False
        # Loading state
        self._loading: bool = False

    def _t(self, key: str, **kwargs) -> str:
        """Translate a string key via i18n, with fallback to the key itself."""
        if self._i18n and hasattr(self._i18n, 't'):
            return self._i18n.t(key, **kwargs)
        return key
        self._loading_thread: threading.Thread | None = None

    def set_header(self, header: str) -> None:
        """Set a persistent header (no-op -- banner is built-in)."""
        self._header_text = header

    def set_version(self, version: str) -> None:
        """Set version string for the banner."""
        self._version = version

    # =====================================================================
    # Text input within curses
    # =====================================================================

    def text_input(self, prompt: str, title: str = "") -> str | None:
        """Text input field WITHIN curses.

        Shows banner + box + prompt + cursor. Returns the entered text,
        or ``None`` if Esc is pressed (back).
        """
        if _IS_WINDOWS:
            return self._text_input_ansi(prompt, title)

        text = ""
        self._enter_interactive()
        try:
            while True:
                self._render_text_input(text, prompt, title)
                key = self._read_key()

                if key == KEY_ENTER:
                    return text if text.strip() else None
                elif key == KEY_ESC:
                    return None
                elif key == KEY_BACKSPACE:
                    text = text[:-1]
                elif key == KEY_SPACE:
                    text += " "
                elif len(key) == 1 and key.isprintable():
                    text += key
        except (KeyboardInterrupt, EOFError):
            return None
        finally:
            self._exit_interactive()

    def _render_text_input(self, text: str, prompt: str, title: str) -> None:
        """Render the text input screen inside curses."""
        import curses

        stdscr = self._stdscr
        if stdscr is None:
            return

        stdscr.erase()
        w, h = self._get_screen_size()
        box_width = min(w - 2, 80)
        box_x = max((w - box_width) // 2, 0)

        y = 0

        # -- Banner --
        y = self._draw_banner(y, w)
        y += 1

        # -- Box top --
        y = self._draw_box_top(y, box_x, box_width, title or "Input")
        y = self._draw_box_empty(y, box_x, box_width)

        # -- Prompt text --
        y = self._draw_box_line_raw(
            y, box_x, box_width,
            [("  ", self._attr_normal()), (prompt, self._attr_white_bold())],
        )
        y = self._draw_box_empty(y, box_x, box_width)

        # -- Input field --
        # Draw a highlighted input area
        inner_avail = box_width - 8  # some padding
        display_text = text
        if len(display_text) > inner_avail:
            display_text = display_text[-(inner_avail - 1):]

        field_segments: list[tuple[str, int]] = [
            ("  > ", self._attr_cyan_bold()),
            (display_text, self._attr_white_bold()),
            ("_", self._attr_cyan_bold()),
        ]
        y = self._draw_box_line_raw(y, box_x, box_width, field_segments)
        y = self._draw_box_empty(y, box_x, box_width)
        y = self._draw_box_empty(y, box_x, box_width)

        # -- Footer --
        footer_segments: list[tuple[str, int]] = [
            ("  ", self._attr_normal()),
            ("Enter", self._attr_white_bold()),
            (" confirm  ", self._attr_dim()),
            ("Esc", self._attr_white_bold()),
            (" back", self._attr_dim()),
        ]
        y = self._draw_box_line_raw(y, box_x, box_width, footer_segments)
        y = self._draw_box_empty(y, box_x, box_width)

        # -- Box bottom --
        y = self._draw_box_bottom(y, box_x, box_width)

        stdscr.refresh()

    def _text_input_ansi(self, prompt: str, title: str) -> str | None:
        """Text input using ANSI escapes (Windows fallback)."""
        sz = shutil.get_terminal_size((80, 24))
        w = max(sz.columns, 60)
        text = ""

        while True:
            out: list[str] = [_CLEAR_SCREEN]
            for line in BANNER_LINES_COMPACT:
                pad = (w - len(line)) // 2
                out.append(f"{_BOLD}{_FG_CYAN}{' ' * max(pad, 0)}{line}{_RESET}")
            out.append("")
            out.append(f"  {_BOLD}{_FG_CYAN}{title or 'Input'}{_RESET}")
            out.append(f"  {_FG_CYAN}{H_LINE * min(w - 4, 60)}{_RESET}")
            out.append("")
            out.append(f"  {_BOLD}{prompt}{_RESET}")
            out.append("")
            out.append(f"  {_BOLD}{_FG_CYAN}>{_RESET} {_BOLD}{text}{_RESET}_")
            out.append("")
            out.append(
                f"  {_BOLD}Enter{_RESET}{_DIM} confirm  {_RESET}"
                f"{_BOLD}Esc{_RESET}{_DIM} back{_RESET}"
            )
            try:
                sys.stdout.write("\n".join(out) + "\n")
                sys.stdout.flush()
            except (OSError, IOError):
                pass

            key = _read_key_windows()
            if key == KEY_ENTER:
                return text
            elif key == KEY_ESC:
                return None
            elif key == KEY_BACKSPACE:
                text = text[:-1]
            elif len(key) == 1 and key.isprintable():
                text += key

    # =====================================================================
    # Loading spinner within curses
    # =====================================================================

    def show_loading(self, message: str, title: str = "") -> None:
        """Show a loading/spinner screen within curses.

        Call this from the main thread before starting background work.
        The spinner runs in a separate thread until :meth:`hide_loading`
        is called.
        """
        self._loading = True
        self._enter_interactive()

        def _spin() -> None:
            frames = ["   ", ".  ", ".. ", "...", " ..", "  .", "   "]
            idx = 0
            while self._loading:
                self._render_loading(message, title, frames[idx % len(frames)])
                idx += 1
                time.sleep(0.3)

        self._loading_thread = threading.Thread(target=_spin, daemon=True)
        self._loading_thread.start()

    def hide_loading(self) -> None:
        """Stop the loading screen and restore the terminal.

        Safe to call multiple times -- subsequent calls are no-ops.
        """
        if not self._loading and self._loading_thread is None:
            return
        self._loading = False
        if self._loading_thread is not None:
            self._loading_thread.join(timeout=2.0)
            self._loading_thread = None
        if self._stdscr is not None or _IS_WINDOWS:
            self._exit_interactive()

    def _render_loading(self, message: str, title: str, spinner: str) -> None:
        """Render the loading spinner screen inside curses."""
        if _IS_WINDOWS:
            self._render_loading_ansi(message, title, spinner)
            return

        import curses

        stdscr = self._stdscr
        if stdscr is None:
            return

        try:
            stdscr.erase()
            w, h = self._get_screen_size()
            box_width = min(w - 2, 60)
            box_x = max((w - box_width) // 2, 0)

            y = 0

            # -- Banner --
            y = self._draw_banner(y, w)
            y += 1

            # -- Box top --
            y = self._draw_box_top(y, box_x, box_width, title or "Loading")
            y = self._draw_box_empty(y, box_x, box_width)
            y = self._draw_box_empty(y, box_x, box_width)

            # -- Spinner + message --
            y = self._draw_box_line_raw(
                y, box_x, box_width,
                [
                    ("    ", self._attr_normal()),
                    (spinner, self._attr_cyan_bold()),
                    ("  ", self._attr_normal()),
                    (message, self._attr_white_bold()),
                ],
            )
            y = self._draw_box_empty(y, box_x, box_width)
            y = self._draw_box_empty(y, box_x, box_width)

            # -- Box bottom --
            y = self._draw_box_bottom(y, box_x, box_width)

            stdscr.refresh()
        except Exception:
            pass  # curses may raise if terminal resized during loading

    def _render_loading_ansi(self, message: str, title: str, spinner: str) -> None:
        """Render loading screen with ANSI codes (Windows fallback)."""
        sz = shutil.get_terminal_size((80, 24))
        w = max(sz.columns, 60)
        out: list[str] = [_CLEAR_SCREEN]
        for line in BANNER_LINES_COMPACT:
            pad = (w - len(line)) // 2
            out.append(f"{_BOLD}{_FG_CYAN}{' ' * max(pad, 0)}{line}{_RESET}")
        out.append("")
        out.append(f"  {_BOLD}{_FG_CYAN}{title or 'Loading'}{_RESET}")
        out.append(f"  {_FG_CYAN}{H_LINE * min(w - 4, 40)}{_RESET}")
        out.append("")
        out.append(f"    {_BOLD}{_FG_CYAN}{spinner}{_RESET}  {_BOLD}{message}{_RESET}")
        out.append("")
        try:
            sys.stdout.write("\n".join(out) + "\n")
            sys.stdout.flush()
        except (OSError, IOError):
            pass

    # =====================================================================
    # Search results table selector
    # =====================================================================

    def select_search_results(
        self,
        results: list[dict],
        title: str = "Select a title",
    ) -> int | None:
        """Select from search results displayed as a formatted table.

        Each result dict must have keys: ``type``, ``title``, ``year``,
        ``service``.

        Returns the selected index or ``None`` if cancelled.
        """
        if not results:
            return None

        # Build plain-text labels for filtering
        labels = [
            f"{r.get('type', '')} {r.get('title', '')} {r.get('year', '')} {r.get('service', '')}"
            for r in results
        ]
        state = _ListState(items=labels)
        page = self._page_size()

        self._enter_interactive()
        try:
            while True:
                page = self._page_size()
                self._render_search_results(state, results, title, page)
                key = self._read_key()

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
            self._exit_interactive()

    def _render_search_results(
        self,
        state: _ListState,
        results: list[dict],
        title: str,
        page: int,
    ) -> None:
        """Render search results as a table with aligned columns."""
        if _IS_WINDOWS:
            self._render_search_results_ansi(state, results, title, page)
            return

        import curses

        stdscr = self._stdscr
        if stdscr is None:
            return

        stdscr.erase()
        w, h = self._get_screen_size()
        box_width = min(w - 2, 110)
        box_x = max((w - box_width) // 2, 0)

        # Column widths: #(4) + Type(7) + Year(6) + Service(8) + gaps(~10) + borders(4)
        # Title gets the rest
        inner = box_width - 4  # content area inside box borders + padding
        col_num = 4    # "  1."
        col_type = 7   # "FILM   " / "SERIE  " / "ANIME  "
        col_year = 6   # "2006  "
        col_svc = 4    # abbreviation
        # Calculate max service width
        for r in results:
            svc = r.get("service", "")
            col_svc = max(col_svc, len(svc))
        col_svc = min(col_svc, 20)

        fixed = col_num + 1 + col_type + 1 + col_year + 1 + col_svc + 3  # +3 for cursor prefix
        col_title = max(10, inner - fixed)

        y = 0

        # -- Banner --
        y = self._draw_banner(y, w)
        y += 1

        # -- Box top --
        y = self._draw_box_top(y, box_x, box_width, title)
        y = self._draw_box_empty(y, box_x, box_width)

        # -- Filter bar --
        if state.filter_text:
            match_word = "matches" if state.visible_count != 1 else "match"
            y = self._draw_box_line_raw(
                y, box_x, box_width,
                [
                    ("  / ", self._attr_cyan_bold()),
                    (state.filter_text, self._attr_white_bold()),
                    ("_", self._attr_cyan_bold()),
                    (f"  ({state.visible_count} {match_word})", self._attr_dim()),
                ],
            )
            y = self._draw_box_empty(y, box_x, box_width)

        # -- Column header --
        hdr_segments: list[tuple[str, int]] = [
            ("   ", self._attr_normal()),  # cursor space
            (f"{'#':<{col_num}}", self._attr_dim()),
            (" ", self._attr_normal()),
            (f"{'Type':<{col_type}}", self._attr_dim()),
            (" ", self._attr_normal()),
            (f"{'Title':<{col_title}}", self._attr_dim()),
            (" ", self._attr_normal()),
            (f"{'Year':<{col_year}}", self._attr_dim()),
            (" ", self._attr_normal()),
            (f"{'Service':<{col_svc}}", self._attr_dim()),
        ]
        y = self._draw_box_line_raw(y, box_x, box_width, hdr_segments)

        # -- Header underline --
        sep_segments: list[tuple[str, int]] = [
            ("   ", self._attr_normal()),
            (H_LINE * col_num, self._attr_dim()),
            (" ", self._attr_normal()),
            (H_LINE * col_type, self._attr_dim()),
            (" ", self._attr_normal()),
            (H_LINE * col_title, self._attr_dim()),
            (" ", self._attr_normal()),
            (H_LINE * col_year, self._attr_dim()),
            (" ", self._attr_normal()),
            (H_LINE * col_svc, self._attr_dim()),
        ]
        y = self._draw_box_line_raw(y, box_x, box_width, sep_segments)

        visible = state.filtered_indices
        total = len(visible)
        state._fix_scroll(page)
        start = state.scroll_offset
        end = min(start + page, total)

        # -- Scroll up indicator --
        if start > 0:
            y = self._draw_box_line_raw(
                y, box_x, box_width,
                [(f"  {UP_ARROW} {start} more above", self._attr_dim())],
            )

        # -- Items --
        for vi in range(start, end):
            real_idx = visible[vi]
            is_cursor = vi == state.cursor
            r = results[real_idx]

            r_type = r.get("type", "").upper()
            r_title = r.get("title", "")
            r_year = str(r.get("year", "")) if r.get("year") else ""
            r_svc = r.get("service", "")

            # Truncate title if needed
            if len(r_title) > col_title:
                r_title = r_title[: col_title - 3] + "..."

            segments: list[tuple[str, int]] = []

            # Cursor arrow
            if is_cursor:
                segments.append((" > ", self._attr_cyan_bold()))
            else:
                segments.append(("   ", self._attr_normal()))

            # Number
            segments.append((f"{real_idx + 1:<{col_num}}", self._attr_dim()))
            segments.append((" ", self._attr_normal()))

            # Type badge
            if r_type in ("FILM", "SERIE", "ANIME"):
                segments.append(
                    (f" {r_type:<{col_type - 1}}", self._badge_attr(r_type))
                )
            else:
                type_style = self._attr_dim()
                segments.append((f"{r_type:<{col_type}}", type_style))
            segments.append((" ", self._attr_normal()))

            # Title
            title_style = self._attr_white_bold() if is_cursor else self._attr_normal()
            segments.append((f"{r_title:<{col_title}}", title_style))
            segments.append((" ", self._attr_normal()))

            # Year
            year_style = self._attr_dim()
            segments.append((f"{r_year:<{col_year}}", year_style))
            segments.append((" ", self._attr_normal()))

            # Service
            segments.append((f"{r_svc:<{col_svc}}", self._attr_dim()))

            y = self._draw_box_line_raw(y, box_x, box_width, segments)

        # -- No results --
        if total == 0:
            y = self._draw_box_line_raw(
                y, box_x, box_width,
                [("  No matches found", self._attr_dim())],
            )

        # -- Scroll down indicator --
        remaining_below = total - end
        if remaining_below > 0:
            y = self._draw_box_line_raw(
                y, box_x, box_width,
                [(f"  {DOWN_ARROW} {remaining_below} more below", self._attr_dim())],
            )

        y = self._draw_box_empty(y, box_x, box_width)

        # -- Footer --
        y = self._draw_footer(y, box_x, box_width, multi=False)
        y = self._draw_box_empty(y, box_x, box_width)

        # -- Box bottom --
        y = self._draw_box_bottom(y, box_x, box_width)

        stdscr.refresh()

    def _render_search_results_ansi(
        self,
        state: _ListState,
        results: list[dict],
        title: str,
        page: int,
    ) -> None:
        """Render search results table using ANSI escapes (Windows fallback)."""
        sz = shutil.get_terminal_size((80, 24))
        w = max(sz.columns, 60)

        col_num = 4
        col_type = 7
        col_year = 6
        col_svc = 4
        for r in results:
            col_svc = max(col_svc, len(r.get("service", "")))
        col_svc = min(col_svc, 20)
        inner = min(w - 4, 106)
        fixed = col_num + 1 + col_type + 1 + col_year + 1 + col_svc + 3
        col_title = max(10, inner - fixed)

        out: list[str] = [_CLEAR_SCREEN]

        for line in BANNER_LINES_COMPACT:
            pad = (w - len(line)) // 2
            out.append(f"{_BOLD}{_FG_CYAN}{' ' * max(pad, 0)}{line}{_RESET}")
        out.append("")
        out.append(f"  {_BOLD}{_FG_CYAN}{title}{_RESET}")
        out.append(f"  {_FG_CYAN}{H_LINE * min(w - 4, 80)}{_RESET}")

        if state.filter_text:
            match_word = "matches" if state.visible_count != 1 else "match"
            out.append(
                f"  {_BOLD}{_FG_CYAN}/{_RESET} "
                f"{_BOLD}{state.filter_text}{_RESET}_"
                f"  {_DIM}({state.visible_count} {match_word}){_RESET}"
            )
            out.append("")

        # Header
        out.append(
            f"   {_DIM}{'#':<{col_num}} {'Type':<{col_type}} "
            f"{'Title':<{col_title}} {'Year':<{col_year}} "
            f"{'Service':<{col_svc}}{_RESET}"
        )
        out.append(
            f"   {_DIM}{H_LINE * col_num} {H_LINE * col_type} "
            f"{H_LINE * col_title} {H_LINE * col_year} "
            f"{H_LINE * col_svc}{_RESET}"
        )

        visible = state.filtered_indices
        total = len(visible)
        state._fix_scroll(page)
        start = state.scroll_offset
        end = min(start + page, total)

        if start > 0:
            out.append(f"  {_DIM}{UP_ARROW} {start} more above{_RESET}")

        for vi in range(start, end):
            real_idx = visible[vi]
            is_cursor = vi == state.cursor
            r = results[real_idx]

            r_type = r.get("type", "").upper()
            r_title = r.get("title", "")
            r_year = str(r.get("year", "")) if r.get("year") else ""
            r_svc = r.get("service", "")

            if len(r_title) > col_title:
                r_title = r_title[: col_title - 3] + "..."

            cursor = f" {_BOLD}{_FG_CYAN}>{_RESET} " if is_cursor else "   "

            badge_colors = {
                "FILM": (_BG_BLUE, _FG_BRIGHT_WHITE),
                "SERIE": (_BG_MAGENTA, _FG_BRIGHT_WHITE),
                "ANIME": (_BG_RED, _FG_BRIGHT_WHITE),
            }
            if r_type in badge_colors:
                bg, fg = badge_colors[r_type]
                type_str = f"{bg}{fg}{_BOLD} {r_type:<{col_type - 1}}{_RESET}"
            else:
                type_str = f"{_DIM}{r_type:<{col_type}}{_RESET}"

            title_style = f"{_BOLD}" if is_cursor else ""

            line = (
                f"{cursor}"
                f"{_DIM}{real_idx + 1:<{col_num}}{_RESET} "
                f"{type_str} "
                f"{title_style}{r_title:<{col_title}}{_RESET} "
                f"{_DIM}{r_year:<{col_year}}{_RESET} "
                f"{_DIM}{r_svc:<{col_svc}}{_RESET}"
            )
            out.append(line)

        if total == 0:
            out.append(f"  {_DIM}No matches found{_RESET}")

        remaining = total - end
        if remaining > 0:
            out.append(f"  {_DIM}{DOWN_ARROW} {remaining} more below{_RESET}")

        out.append("")
        out.append(
            f"  {_BOLD}Enter{_RESET}{_DIM} confirm  {_RESET}"
            f"{_BOLD}Esc{_RESET}{_DIM} back  {_RESET}"
            f"{_BOLD}/{_RESET}{_DIM} filter{_RESET}"
        )

        try:
            sys.stdout.write("\n".join(out) + "\n")
            sys.stdout.flush()
        except (OSError, IOError):
            pass

    # =====================================================================
    # Terminal setup/teardown
    # =====================================================================

    def _enter_interactive(self) -> None:
        """Set up terminal for interactive input."""
        if _IS_WINDOWS:
            sys.stdout.write(_HIDE_CURSOR)
            sys.stdout.flush()
            return

        import curses

        stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        stdscr.keypad(True)
        curses.curs_set(0)  # hide cursor

        # Initialize colors
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(_CP_CYAN, curses.COLOR_CYAN, -1)
            curses.init_pair(_CP_WHITE, curses.COLOR_WHITE, -1)
            curses.init_pair(_CP_DIM, curses.COLOR_WHITE, -1)
            curses.init_pair(_CP_BADGE_FILM, curses.COLOR_WHITE, curses.COLOR_BLUE)
            curses.init_pair(_CP_BADGE_SERIE, curses.COLOR_WHITE, curses.COLOR_MAGENTA)
            curses.init_pair(_CP_BADGE_ANIME, curses.COLOR_WHITE, curses.COLOR_RED)
            curses.init_pair(_CP_YELLOW, curses.COLOR_YELLOW, -1)
            curses.init_pair(_CP_RED, curses.COLOR_RED, -1)
            curses.init_pair(_CP_GREEN, curses.COLOR_GREEN, -1)
            self._has_colors = True
        except curses.error:
            self._has_colors = False

        self._stdscr = stdscr

    def _exit_interactive(self) -> None:
        """Restore terminal state."""
        if _IS_WINDOWS:
            try:
                sys.stdout.write(_SHOW_CURSOR + _CLEAR_SCREEN)
                sys.stdout.flush()
            except (OSError, IOError):
                pass
            return

        import curses

        try:
            curses.endwin()
        except curses.error:
            pass
        self._stdscr = None

        # curses.endwin() exits the alternate screen that curses used,
        # which also exits the TerminalManager's alternate screen.
        # Re-enter it so subsequent output stays clean.
        try:
            sys.stdout.write("\033[?1049h\033[H\033[2J")
            sys.stdout.flush()
        except (OSError, IOError):
            pass

    def _read_key(self) -> str:
        """Read a single keypress."""
        if _IS_WINDOWS:
            return _read_key_windows()
        return self._read_key_curses()

    def _read_key_curses(self) -> str:
        """Read a single keypress via curses."""
        import curses

        stdscr = self._stdscr
        if stdscr is None:
            return ""

        try:
            ch = stdscr.getch()
        except curses.error:
            return ""
        except KeyboardInterrupt:
            raise

        if ch == curses.KEY_UP:
            return KEY_UP
        if ch == curses.KEY_DOWN:
            return KEY_DOWN
        if ch == curses.KEY_LEFT:
            return "left"
        if ch == curses.KEY_RIGHT:
            return "right"
        if ch == curses.KEY_PPAGE:
            return KEY_PAGE_UP
        if ch == curses.KEY_NPAGE:
            return KEY_PAGE_DOWN
        if ch == curses.KEY_HOME:
            return KEY_HOME
        if ch == curses.KEY_END:
            return KEY_END
        if ch == curses.KEY_BTAB:
            return KEY_SHIFT_TAB
        if ch in (curses.KEY_ENTER, 10, 13):
            return KEY_ENTER
        if ch == 32:
            return KEY_SPACE
        if ch == 9:
            return KEY_TAB
        if ch == 27:
            # ESC key -- check if it's the start of an escape sequence
            stdscr.nodelay(True)
            try:
                next_ch = stdscr.getch()
            except curses.error:
                next_ch = -1
            stdscr.nodelay(False)
            if next_ch == -1:
                return KEY_ESC
            # It was part of an escape sequence, consume remaining bytes
            stdscr.nodelay(True)
            try:
                while True:
                    extra = stdscr.getch()
                    if extra == -1:
                        break
            except curses.error:
                pass
            stdscr.nodelay(False)
            return KEY_ESC
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            return KEY_BACKSPACE
        if ch == 3:
            raise KeyboardInterrupt
        if ch == 4:  # Ctrl+D
            raise KeyboardInterrupt
        if ch < 32:
            return ""

        try:
            return chr(ch)
        except (ValueError, OverflowError):
            return ""

    # =====================================================================
    # Curses rendering helpers
    # =====================================================================

    def _safe_addstr(
        self, y: int, x: int, text: str, attr: int = 0, max_x: int = 0
    ) -> None:
        """Safely write a string to the curses screen, clipping to bounds.

        Handles the curses quirk where writing to the last cell of the screen
        raises an error.
        """
        import curses

        stdscr = self._stdscr
        if stdscr is None:
            return

        max_y, screen_max_x = stdscr.getmaxyx()
        if y < 0 or y >= max_y:
            return
        if x >= screen_max_x:
            return

        clip_x = max_x if max_x > 0 else screen_max_x
        avail = clip_x - x
        if avail <= 0:
            return

        # Truncate text to fit
        if len(text) > avail:
            text = text[: avail - 1] + "\u2026" if avail > 1 else text[:avail]

        try:
            stdscr.addstr(y, x, text, attr)
        except curses.error:
            # Writing to last position on screen raises error; ignore
            pass

    def _attr_cyan(self) -> int:
        import curses

        if self._has_colors:
            return curses.color_pair(_CP_CYAN)
        return 0

    def _attr_cyan_bold(self) -> int:
        import curses

        if self._has_colors:
            return curses.color_pair(_CP_CYAN) | curses.A_BOLD
        return curses.A_BOLD

    def _attr_white_bold(self) -> int:
        import curses

        if self._has_colors:
            return curses.color_pair(_CP_WHITE) | curses.A_BOLD
        return curses.A_BOLD

    def _attr_dim(self) -> int:
        import curses

        if self._has_colors:
            return curses.color_pair(_CP_DIM) | curses.A_DIM
        return curses.A_DIM

    def _attr_normal(self) -> int:
        import curses

        if self._has_colors:
            return curses.color_pair(_CP_WHITE)
        return 0

    def _attr_yellow(self) -> int:
        import curses

        if self._has_colors:
            return curses.color_pair(_CP_YELLOW)
        return 0

    def _attr_yellow_bold(self) -> int:
        import curses

        if self._has_colors:
            return curses.color_pair(_CP_YELLOW) | curses.A_BOLD
        return curses.A_BOLD

    def _attr_red_bold(self) -> int:
        import curses

        if self._has_colors:
            return curses.color_pair(_CP_RED) | curses.A_BOLD
        return curses.A_BOLD

    def _badge_attr(self, badge_type: str) -> int:
        import curses

        if not self._has_colors:
            return curses.A_BOLD

        badge_map = {
            "FILM": _CP_BADGE_FILM,
            "SERIE": _CP_BADGE_SERIE,
            "ANIME": _CP_BADGE_ANIME,
        }
        cp = badge_map.get(badge_type, _CP_WHITE)
        return curses.color_pair(cp) | curses.A_BOLD

    # =====================================================================
    # Curses screen drawing routines
    # =====================================================================

    def _draw_banner(self, y: int, width: int) -> int:
        """Draw the centered banner at row y. Returns next row.

        Uses the large block-character banner when the terminal is at least
        90 columns wide; otherwise falls back to the compact version.
        """
        banner = BANNER_LINES_LARGE if width >= 90 else BANNER_LINES_COMPACT
        for line in banner:
            pad = (width - len(line)) // 2
            self._safe_addstr(y, max(pad, 0), line, self._attr_cyan_bold())
            y += 1

        # Version / tagline
        if self._version:
            ver_text = f"v{self._version}  |  Professional Media Downloader"
        else:
            ver_text = "Professional Media Downloader"
        ver_pad = (width - len(ver_text)) // 2
        self._safe_addstr(y, max(ver_pad, 0), ver_text, self._attr_dim())
        y += 1
        return y

    def _draw_hline(self, y: int, x: int, width: int) -> None:
        """Draw a horizontal line of H_LINE characters."""
        self._safe_addstr(y, x, H_LINE * width, self._attr_cyan())

    def _draw_box_top(self, y: int, x: int, width: int, title: str) -> int:
        """Draw box top border with centered title. Returns next row."""
        import curses

        inner = width - 2
        title_clean = f" {title} "
        title_len = len(title_clean)
        left = (inner - title_len) // 2
        right = inner - title_len - left

        self._safe_addstr(y, x, "\u256d", self._attr_cyan_bold())
        self._safe_addstr(y, x + 1, H_LINE * left, self._attr_cyan_bold())
        self._safe_addstr(y, x + 1 + left, title_clean, self._attr_white_bold())
        self._safe_addstr(
            y, x + 1 + left + title_len, H_LINE * right, self._attr_cyan_bold()
        )
        self._safe_addstr(y, x + width - 1, "\u256e", self._attr_cyan_bold())
        return y + 1

    def _draw_box_bottom(self, y: int, x: int, width: int) -> int:
        """Draw box bottom border. Returns next row."""
        inner = width - 2
        self._safe_addstr(y, x, "\u2570", self._attr_cyan_bold())
        self._safe_addstr(y, x + 1, H_LINE * inner, self._attr_cyan_bold())
        self._safe_addstr(y, x + width - 1, "\u256f", self._attr_cyan_bold())
        return y + 1

    def _draw_box_line_raw(
        self, y: int, x: int, width: int, segments: list[tuple[str, int]]
    ) -> int:
        """Draw a line inside a box with side borders.

        ``segments`` is a list of (text, attr) tuples to write sequentially
        inside the box content area. Returns next row.
        """
        inner = width - 2
        self._safe_addstr(y, x, "\u2502", self._attr_cyan())
        self._safe_addstr(y, x + width - 1, "\u2502", self._attr_cyan())

        # Write segments
        cx = x + 2  # start content after border + 1 space
        max_cx = x + width - 2
        for text, attr in segments:
            if cx >= max_cx:
                break
            avail = max_cx - cx
            t = text[:avail]
            self._safe_addstr(y, cx, t, attr)
            cx += len(t)

        return y + 1

    def _draw_box_empty(self, y: int, x: int, width: int) -> int:
        """Draw an empty line inside a box. Returns next row."""
        self._safe_addstr(y, x, "\u2502", self._attr_cyan())
        self._safe_addstr(y, x + width - 1, "\u2502", self._attr_cyan())
        return y + 1

    def _draw_box_separator(self, y: int, x: int, width: int) -> int:
        """Draw a horizontal separator inside a box. Returns next row."""
        inner = width - 2
        self._safe_addstr(y, x, "\u251c", self._attr_cyan())
        self._safe_addstr(y, x + 1, H_LINE * inner, self._attr_cyan())
        self._safe_addstr(y, x + width - 1, "\u2524", self._attr_cyan())
        return y + 1

    # =====================================================================
    # Page size calculations
    # =====================================================================

    def _get_screen_size(self) -> tuple[int, int]:
        """Return (width, height) of the current terminal."""
        if _IS_WINDOWS or self._stdscr is None:
            sz = shutil.get_terminal_size((80, 24))
            return max(sz.columns, 60), max(sz.lines, 16)
        max_y, max_x = self._stdscr.getmaxyx()
        return max(max_x, 60), max(max_y, 16)

    def _banner_height(self, width: int) -> int:
        """Return the number of rows the banner occupies (lines + version)."""
        if width >= 90:
            return len(BANNER_LINES_LARGE) + 1  # 7
        return len(BANNER_LINES_COMPACT) + 1  # 4

    def _page_size(self) -> int:
        w, h = self._get_screen_size()
        banner_h = self._banner_height(w)
        # Reserve: banner + title(2) + filter(2) + footer(3) + border(4) + padding(4)
        overhead = banner_h + 15
        return max(3, h - overhead)

    def _page_size_tracks(self) -> int:
        w, h = self._get_screen_size()
        banner_h = self._banner_height(w)
        per_section = (h - banner_h - 18) // 3
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

        # Strip Rich markup from all items
        clean_items = [_strip_rich_markup(item) for item in items]
        state = _ListState(items=clean_items)
        page = self._page_size()

        self._enter_interactive()
        try:
            while True:
                page = self._page_size()
                self._render_list(
                    state, title, page, multi=False, badge=show_type_badge
                )
                key = self._read_key()

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
            self._exit_interactive()

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

        self._enter_interactive()
        try:
            while True:
                page = self._page_size()
                self._render_list(
                    state,
                    title or "Select episodes",
                    page,
                    multi=True,
                    show_count=True,
                )
                key = self._read_key()

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
            self._exit_interactive()

    def select_tracks(
        self,
        bundle: StreamBundle,
        preferred_audio: str = "",
        preferred_subtitle: str = "",
    ) -> SelectedTracks | None:
        """All-in-one track selection.

        Shows three sections -- Video, Audio, Subtitles -- with Tab to
        navigate between them. Returns :class:`SelectedTracks` or ``None``.
        """
        if not bundle.video:
            return None

        video_labels = [_strip_rich_markup(t.label) for t in bundle.video]
        audio_labels = [_strip_rich_markup(t.label) for t in bundle.audio]
        sub_labels = [_strip_rich_markup(t.label) for t in bundle.subtitles]

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

        self._enter_interactive()
        try:
            while True:
                page = self._page_size_tracks()
                self._render_tracks(sections, bundle, page)
                key = self._read_key()

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
            self._exit_interactive()

    # =====================================================================
    # Rendering -- single / multi list (curses)
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
        """Render a scrollable, filterable list using curses."""
        if _IS_WINDOWS:
            self._render_list_ansi(
                state, title, page, multi=multi, badge=badge, show_count=show_count
            )
            return

        import curses

        stdscr = self._stdscr
        if stdscr is None:
            return

        stdscr.erase()
        w, h = self._get_screen_size()
        box_width = min(w - 2, 100)
        box_x = max((w - box_width) // 2, 0)

        y = 0

        # -- Banner --
        y = self._draw_banner(y, w)
        y += 1  # spacing

        # -- Box top --
        y = self._draw_box_top(y, box_x, box_width, title)
        y = self._draw_box_empty(y, box_x, box_width)

        # -- Filter bar --
        if state.filter_text:
            match_word = "matches" if state.visible_count != 1 else "match"
            y = self._draw_box_line_raw(
                y,
                box_x,
                box_width,
                [
                    ("  / ", self._attr_cyan_bold()),
                    (state.filter_text, self._attr_white_bold()),
                    ("_", self._attr_cyan_bold()),
                    (
                        f"  ({state.visible_count} {match_word})",
                        self._attr_dim(),
                    ),
                ],
            )
            y = self._draw_box_empty(y, box_x, box_width)

        visible = state.filtered_indices
        total = len(visible)

        state._fix_scroll(page)
        start = state.scroll_offset
        end = min(start + page, total)

        # -- Scroll up indicator --
        if start > 0:
            y = self._draw_box_line_raw(
                y,
                box_x,
                box_width,
                [
                    (f"  {UP_ARROW} {start} more above", self._attr_dim()),
                ],
            )

        # -- Items --
        for vi in range(start, end):
            real_idx = visible[vi]
            is_cursor = vi == state.cursor
            is_selected = real_idx in state.selected
            raw_label = state.items[real_idx]

            segments: list[tuple[str, int]] = []

            # Cursor arrow
            if is_cursor:
                segments.append((" > ", self._attr_cyan_bold()))
            else:
                segments.append(("   ", self._attr_normal()))

            # Checkbox / radio
            if multi:
                if is_selected:
                    segments.append(("[x]", self._attr_cyan_bold()))
                else:
                    segments.append(("[ ]", self._attr_dim()))
            else:
                if is_selected or is_cursor:
                    segments.append(("(*)", self._attr_cyan_bold()))
                else:
                    segments.append(("( )", self._attr_dim()))

            segments.append((" ", self._attr_normal()))

            # Number
            segments.append((f"{real_idx + 1:>3}. ", self._attr_dim()))

            # Badge extraction
            if badge:
                label_text, badge_type = _extract_badge(raw_label)
                if badge_type:
                    segments.append(
                        (f" {badge_type} ", self._badge_attr(badge_type))
                    )
                    segments.append((" ", self._attr_normal()))
                style = self._attr_white_bold() if is_cursor else self._attr_normal()
                segments.append((label_text, style))
            else:
                style = self._attr_white_bold() if is_cursor else self._attr_normal()
                segments.append((raw_label, style))

            y = self._draw_box_line_raw(y, box_x, box_width, segments)

        # -- No results --
        if total == 0:
            y = self._draw_box_line_raw(
                y,
                box_x,
                box_width,
                [("  No matches found", self._attr_dim())],
            )

        # -- Scroll down indicator --
        remaining_below = total - end
        if remaining_below > 0:
            y = self._draw_box_line_raw(
                y,
                box_x,
                box_width,
                [
                    (
                        f"  {DOWN_ARROW} {remaining_below} more below",
                        self._attr_dim(),
                    ),
                ],
            )

        y = self._draw_box_empty(y, box_x, box_width)

        # -- Selected count --
        if show_count and multi:
            y = self._draw_box_line_raw(
                y,
                box_x,
                box_width,
                [
                    (f"  {len(state.selected)} selected", self._attr_cyan_bold()),
                ],
            )

        # -- Footer --
        y = self._draw_footer(y, box_x, box_width, multi)

        y = self._draw_box_empty(y, box_x, box_width)

        # -- Box bottom --
        y = self._draw_box_bottom(y, box_x, box_width)

        stdscr.refresh()

    def _draw_footer(self, y: int, x: int, width: int, multi: bool) -> int:
        """Draw the keybinding footer line inside the box."""
        segments: list[tuple[str, int]] = [("  ", self._attr_normal())]

        if multi:
            segments.append(("Space", self._attr_white_bold()))
            segments.append((" toggle  ", self._attr_dim()))
            segments.append(("a", self._attr_white_bold()))
            segments.append((" all  ", self._attr_dim()))
            segments.append(("n", self._attr_white_bold()))
            segments.append((" none  ", self._attr_dim()))

        segments.append(("Enter", self._attr_white_bold()))
        segments.append((" confirm  ", self._attr_dim()))
        segments.append(("Esc", self._attr_white_bold()))
        segments.append((" back  ", self._attr_dim()))
        segments.append(("/", self._attr_white_bold()))
        segments.append((" filter", self._attr_dim()))

        return self._draw_box_line_raw(y, x, width, segments)

    # =====================================================================
    # Rendering -- track selector (curses)
    # =====================================================================

    def _render_tracks(
        self,
        sections: _TrackSections,
        bundle: StreamBundle,
        page: int,
    ) -> None:
        """Render the all-in-one track selector using curses."""
        if _IS_WINDOWS:
            self._render_tracks_ansi(sections, bundle, page)
            return

        import curses

        stdscr = self._stdscr
        if stdscr is None:
            return

        stdscr.erase()
        w, h = self._get_screen_size()
        box_width = min(w - 2, 110)
        box_x = max((w - box_width) // 2, 0)

        y = 0

        # -- Banner --
        y = self._draw_banner(y, w)
        y += 1

        # -- Box top --
        y = self._draw_box_top(y, box_x, box_width, self._t("tracks.confirm"))
        y = self._draw_box_empty(y, box_x, box_width)

        section_defs: list[tuple[str, _ListState, bool, str | None]] = [
            (self._t("tracks.video_header"), sections.video, False, self._video_warning(bundle)),
            (self._t("tracks.audio_header"), sections.audio, True, self._audio_warning(bundle)),
            (self._t("tracks.subtitle_header"), sections.subtitles, True, self._subtitle_warning(bundle)),
        ]

        for idx, (label, st, multi, warning) in enumerate(section_defs):
            is_active = idx == sections.active_section

            # Section header
            if is_active:
                header_segments: list[tuple[str, int]] = [
                    (f"  {RIGHT_ARROW} ", self._attr_cyan_bold()),
                    (
                        label,
                        self._attr_cyan_bold()
                        | curses.A_UNDERLINE,
                    ),
                ]
            else:
                header_segments = [
                    ("    ", self._attr_normal()),
                    (label, self._attr_dim() | curses.A_BOLD),
                ]

            # Selected count/info
            if multi:
                count = len(st.selected)
                header_segments.append(
                    (f"  ({count} selected)", self._attr_dim())
                )
            else:
                if st.selected:
                    sel_idx = min(st.selected)
                    if sel_idx < len(st.items):
                        header_segments.append(
                            (f"  = {st.items[sel_idx]}", self._attr_dim())
                        )

            y = self._draw_box_line_raw(y, box_x, box_width, header_segments)

            # Warning
            if warning:
                y = self._draw_box_line_raw(
                    y,
                    box_x,
                    box_width,
                    [("    ", self._attr_normal()), (warning, self._attr_yellow())],
                )

            # Items
            visible = st.filtered_indices
            total = len(visible)

            if total == 0:
                y = self._draw_box_line_raw(
                    y,
                    box_x,
                    box_width,
                    [("      (none)", self._attr_dim())],
                )
            else:
                st._fix_scroll(page)
                start = st.scroll_offset
                end = min(start + page, total)

                if start > 0:
                    y = self._draw_box_line_raw(
                        y,
                        box_x,
                        box_width,
                        [(f"      {UP_ARROW} {start} more", self._attr_dim())],
                    )

                for vi in range(start, end):
                    real_idx = visible[vi]
                    is_cursor = is_active and vi == st.cursor
                    is_selected = real_idx in st.selected
                    raw_label = st.items[real_idx]

                    segments: list[tuple[str, int]] = []

                    if is_cursor:
                        segments.append(("    > ", self._attr_cyan_bold()))
                    else:
                        segments.append(("      ", self._attr_normal()))

                    if multi:
                        if is_selected:
                            segments.append(("[x]", self._attr_cyan_bold()))
                        else:
                            segments.append(("[ ]", self._attr_dim()))
                    else:
                        if is_selected:
                            segments.append(("(*)", self._attr_cyan_bold()))
                        elif is_cursor:
                            segments.append(("( )", self._attr_cyan()))
                        else:
                            segments.append(("( )", self._attr_dim()))

                    segments.append((" ", self._attr_normal()))
                    style = self._attr_white_bold() if is_cursor else self._attr_normal()
                    segments.append((raw_label, style))

                    y = self._draw_box_line_raw(y, box_x, box_width, segments)

                remaining = total - end
                if remaining > 0:
                    y = self._draw_box_line_raw(
                        y,
                        box_x,
                        box_width,
                        [
                            (
                                f"      {DOWN_ARROW} {remaining} more",
                                self._attr_dim(),
                            ),
                        ],
                    )

            # Spacer between sections
            if idx < len(section_defs) - 1:
                y = self._draw_box_empty(y, box_x, box_width)

        # -- Summary --
        y = self._draw_box_empty(y, box_x, box_width)
        y = self._draw_box_line_raw(
            y,
            box_x,
            box_width,
            [(f"  {H_LINE * 40}", self._attr_dim())],
        )
        y = self._draw_box_empty(y, box_x, box_width)

        summary_segments: list[tuple[str, int]] = [
            ("  Selection: ", self._attr_white_bold()),
        ]

        # Video
        if sections.video.selected:
            v_idx = min(sections.video.selected)
            if v_idx < len(bundle.video):
                summary_segments.append(
                    (bundle.video[v_idx].label, self._attr_cyan())
                )
        else:
            summary_segments.append(("(none)", self._attr_red_bold()))

        summary_segments.append(("  |  ", self._attr_dim()))

        # Audio
        a_count = len(sections.audio.selected)
        if a_count:
            summary_segments.append((f"{a_count} audio", self._attr_cyan()))
        else:
            summary_segments.append(("0 audio", self._attr_dim()))

        summary_segments.append(("  |  ", self._attr_dim()))

        # Subtitles
        s_count = len(sections.subtitles.selected)
        if s_count:
            summary_segments.append((f"{s_count} subs", self._attr_cyan()))
        else:
            summary_segments.append(("0 subs", self._attr_dim()))

        y = self._draw_box_line_raw(y, box_x, box_width, summary_segments)

        # -- Footer --
        y = self._draw_box_empty(y, box_x, box_width)
        footer_segments: list[tuple[str, int]] = [
            ("  ", self._attr_normal()),
            ("Tab", self._attr_white_bold()),
            (" section  ", self._attr_dim()),
            ("Space", self._attr_white_bold()),
            (" toggle  ", self._attr_dim()),
            ("Enter", self._attr_white_bold()),
            (" confirm  ", self._attr_dim()),
            ("Esc", self._attr_white_bold()),
            (" cancel", self._attr_dim()),
        ]
        y = self._draw_box_line_raw(y, box_x, box_width, footer_segments)
        y = self._draw_box_empty(y, box_x, box_width)

        # -- Box bottom --
        y = self._draw_box_bottom(y, box_x, box_width)

        stdscr.refresh()

    # =====================================================================
    # Windows ANSI fallback rendering
    # =====================================================================

    def _render_list_ansi(
        self,
        state: _ListState,
        title: str,
        page: int,
        *,
        multi: bool = False,
        badge: bool = False,
        show_count: bool = False,
    ) -> None:
        """Render list using ANSI escape codes (Windows fallback)."""
        sz = shutil.get_terminal_size((80, 24))
        w = max(sz.columns, 60)

        out: list[str] = [_CLEAR_SCREEN]

        # Banner
        banner = BANNER_LINES_LARGE if w >= 90 else BANNER_LINES_COMPACT
        for line in banner:
            pad = (w - len(line)) // 2
            out.append(f"{_BOLD}{_FG_CYAN}{' ' * max(pad, 0)}{line}{_RESET}")
        if self._version:
            ver = f"v{self._version}  |  Professional Media Downloader"
        else:
            ver = "Professional Media Downloader"
        ver_pad = (w - len(ver)) // 2
        out.append(f"{_DIM}{' ' * max(ver_pad, 0)}{ver}{_RESET}")
        out.append("")

        # Title
        out.append(f"  {_BOLD}{_FG_CYAN}{title}{_RESET}")
        out.append(f"  {_FG_CYAN}{H_LINE * min(w - 4, 80)}{_RESET}")

        # Filter
        if state.filter_text:
            match_word = "matches" if state.visible_count != 1 else "match"
            out.append(
                f"  {_BOLD}{_FG_CYAN}/{_RESET} "
                f"{_BOLD}{_FG_WHITE}{state.filter_text}{_RESET}_"
                f"  {_DIM}({state.visible_count} {match_word}){_RESET}"
            )
            out.append("")

        visible = state.filtered_indices
        total = len(visible)
        state._fix_scroll(page)
        start = state.scroll_offset
        end = min(start + page, total)

        if start > 0:
            out.append(f"  {_DIM}{UP_ARROW} {start} more above{_RESET}")

        for vi in range(start, end):
            real_idx = visible[vi]
            is_cursor = vi == state.cursor
            is_selected = real_idx in state.selected
            raw_label = state.items[real_idx]

            line = ""
            if is_cursor:
                line += f" {_BOLD}{_FG_CYAN}>{_RESET} "
            else:
                line += "   "

            if multi:
                if is_selected:
                    line += f"{_BOLD}{_FG_CYAN}[x]{_RESET}"
                else:
                    line += f"{_DIM}[ ]{_RESET}"
            else:
                if is_selected or is_cursor:
                    line += f"{_BOLD}{_FG_CYAN}(*){_RESET}"
                else:
                    line += f"{_DIM}( ){_RESET}"

            line += " "
            line += f"{_DIM}{real_idx + 1:>3}. {_RESET}"

            if badge:
                label_text, badge_type = _extract_badge(raw_label)
                if badge_type:
                    badge_colors = {
                        "FILM": (_BG_BLUE, _FG_BRIGHT_WHITE),
                        "SERIE": (_BG_MAGENTA, _FG_BRIGHT_WHITE),
                        "ANIME": (_BG_RED, _FG_BRIGHT_WHITE),
                    }
                    bg, fg = badge_colors.get(badge_type, ("", ""))
                    line += f"{bg}{fg}{_BOLD} {badge_type} {_RESET} "
                style = f"{_BOLD}{_FG_WHITE}" if is_cursor else ""
                line += f"{style}{label_text}{_RESET}"
            else:
                style = f"{_BOLD}{_FG_WHITE}" if is_cursor else ""
                line += f"{style}{raw_label}{_RESET}"

            out.append(line)

        if total == 0:
            out.append(f"  {_DIM}No matches found{_RESET}")

        remaining_below = total - end
        if remaining_below > 0:
            out.append(f"  {_DIM}{DOWN_ARROW} {remaining_below} more below{_RESET}")

        out.append("")

        if show_count and multi:
            out.append(f"  {_BOLD}{_FG_CYAN}{len(state.selected)} selected{_RESET}")

        # Footer
        foot = "  "
        if multi:
            foot += f"{_BOLD}Space{_RESET}{_DIM} toggle  {_RESET}"
            foot += f"{_BOLD}a{_RESET}{_DIM} all  {_RESET}"
            foot += f"{_BOLD}n{_RESET}{_DIM} none  {_RESET}"
        foot += f"{_BOLD}Enter{_RESET}{_DIM} confirm  {_RESET}"
        foot += f"{_BOLD}Esc{_RESET}{_DIM} back  {_RESET}"
        foot += f"{_BOLD}/{_RESET}{_DIM} filter{_RESET}"
        out.append(foot)

        try:
            sys.stdout.write("\n".join(out) + "\n")
            sys.stdout.flush()
        except (OSError, IOError):
            pass

    def _render_tracks_ansi(
        self,
        sections: _TrackSections,
        bundle: StreamBundle,
        page: int,
    ) -> None:
        """Render track selector using ANSI escape codes (Windows fallback)."""
        sz = shutil.get_terminal_size((80, 24))
        w = max(sz.columns, 60)

        out: list[str] = [_CLEAR_SCREEN]

        # Banner
        banner = BANNER_LINES_LARGE if w >= 90 else BANNER_LINES_COMPACT
        for line in banner:
            pad = (w - len(line)) // 2
            out.append(f"{_BOLD}{_FG_CYAN}{' ' * max(pad, 0)}{line}{_RESET}")
        if self._version:
            ver = f"v{self._version}  |  Professional Media Downloader"
        else:
            ver = "Professional Media Downloader"
        ver_pad = (w - len(ver)) // 2
        out.append(f"{_DIM}{' ' * max(ver_pad, 0)}{ver}{_RESET}")
        out.append("")
        out.append(f"  {_BOLD}{_FG_CYAN}Track Selection{_RESET}")
        out.append(f"  {_FG_CYAN}{H_LINE * min(w - 4, 80)}{_RESET}")

        section_defs: list[tuple[str, _ListState, bool, str | None]] = [
            (self._t("tracks.video_header"), sections.video, False, self._video_warning(bundle)),
            (self._t("tracks.audio_header"), sections.audio, True, self._audio_warning(bundle)),
            (self._t("tracks.subtitle_header"), sections.subtitles, True, self._subtitle_warning(bundle)),
        ]

        for idx, (label, st, multi, warning) in enumerate(section_defs):
            is_active = idx == sections.active_section

            if is_active:
                header = f"  {_BOLD}{_FG_CYAN}{RIGHT_ARROW} {label}{_RESET}"
            else:
                header = f"    {_DIM}{_BOLD}{label}{_RESET}"

            if multi:
                count = len(st.selected)
                header += f"  {_DIM}({count} selected){_RESET}"
            else:
                if st.selected:
                    sel_idx = min(st.selected)
                    if sel_idx < len(st.items):
                        header += f"  {_DIM}= {st.items[sel_idx]}{_RESET}"

            out.append(header)

            if warning:
                out.append(f"    {_FG_YELLOW}{warning}{_RESET}")

            visible = st.filtered_indices
            total = len(visible)

            if total == 0:
                out.append(f"      {_DIM}(none){_RESET}")
            else:
                st._fix_scroll(page)
                start = st.scroll_offset
                end = min(start + page, total)

                if start > 0:
                    out.append(f"      {_DIM}{UP_ARROW} {start} more{_RESET}")

                for vi in range(start, end):
                    real_idx = visible[vi]
                    is_cursor = is_active and vi == st.cursor
                    is_selected = real_idx in st.selected
                    raw_label = st.items[real_idx]

                    line = ""
                    if is_cursor:
                        line += f"    {_BOLD}{_FG_CYAN}> {_RESET}"
                    else:
                        line += "      "

                    if multi:
                        if is_selected:
                            line += f"{_BOLD}{_FG_CYAN}[x]{_RESET}"
                        else:
                            line += f"{_DIM}[ ]{_RESET}"
                    else:
                        if is_selected:
                            line += f"{_BOLD}{_FG_CYAN}(*){_RESET}"
                        elif is_cursor:
                            line += f"{_FG_CYAN}( ){_RESET}"
                        else:
                            line += f"{_DIM}( ){_RESET}"

                    line += " "
                    style = f"{_BOLD}" if is_cursor else ""
                    line += f"{style}{raw_label}{_RESET}"

                    out.append(line)

                remaining = total - end
                if remaining > 0:
                    out.append(f"      {_DIM}{DOWN_ARROW} {remaining} more{_RESET}")

            if idx < len(section_defs) - 1:
                out.append("")

        out.append("")
        out.append(f"  {_DIM}{H_LINE * 40}{_RESET}")
        out.append("")

        summary = f"  {_BOLD}Selection:{_RESET} "
        if sections.video.selected:
            v_idx = min(sections.video.selected)
            if v_idx < len(bundle.video):
                summary += f"{_FG_CYAN}{bundle.video[v_idx].label}{_RESET}"
        else:
            summary += f"{_DIM}{_FG_RED}(none){_RESET}"
        summary += f"  {_DIM}|{_RESET}  "
        a_count = len(sections.audio.selected)
        summary += f"{_FG_CYAN}{a_count} audio{_RESET}" if a_count else f"{_DIM}0 audio{_RESET}"
        summary += f"  {_DIM}|{_RESET}  "
        s_count = len(sections.subtitles.selected)
        summary += f"{_FG_CYAN}{s_count} subs{_RESET}" if s_count else f"{_DIM}0 subs{_RESET}"
        out.append(summary)

        out.append("")
        foot = (
            f"  {_BOLD}Tab{_RESET}{_DIM} section  {_RESET}"
            f"{_BOLD}Space{_RESET}{_DIM} toggle  {_RESET}"
            f"{_BOLD}Enter{_RESET}{_DIM} confirm  {_RESET}"
            f"{_BOLD}Esc{_RESET}{_DIM} cancel{_RESET}"
        )
        out.append(foot)

        try:
            sys.stdout.write("\n".join(out) + "\n")
            sys.stdout.flush()
        except (OSError, IOError):
            pass

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
