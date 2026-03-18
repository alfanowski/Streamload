"""Alternate screen buffer manager for Streamload.

Switches the terminal into the alternate screen buffer on entry and
restores the original buffer on exit.  This keeps the user's scrollback
clean -- after Streamload finishes (or crashes), the terminal looks
exactly as it did before.

Works on macOS, Linux, and Windows (Windows Terminal natively; legacy
``cmd.exe`` via ``SetConsoleMode`` with ``ENABLE_VIRTUAL_TERMINAL_PROCESSING``).

Usage::

    from streamload.cli.terminal import TerminalManager

    with TerminalManager():
        # draw UI in alternate screen ...
        pass
    # original screen is automatically restored
"""

from __future__ import annotations

import atexit
import platform
import signal
import sys

# ---------------------------------------------------------------------------
# ANSI escape sequences
# ---------------------------------------------------------------------------

_ENTER_ALT_SCREEN = "\033[?1049h"
_LEAVE_ALT_SCREEN = "\033[?1049l"
_CURSOR_HOME = "\033[H"
_CLEAR_SCREEN = "\033[2J"


# ---------------------------------------------------------------------------
# Windows helpers
# ---------------------------------------------------------------------------

def _enable_windows_vt_processing() -> bool:
    """Enable ANSI / VT100 escape processing on Windows.

    Calls ``SetConsoleMode`` via :mod:`ctypes` to set
    ``ENABLE_VIRTUAL_TERMINAL_PROCESSING`` on the active console output
    handle.  This is necessary for legacy ``cmd.exe``; Windows Terminal
    already supports it natively.

    Returns ``True`` if VT processing is (now) available, ``False``
    otherwise.
    """
    if platform.system() != "Windows":
        return True  # Unix terminals support VT natively

    try:
        import ctypes
        import ctypes.wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        # STD_OUTPUT_HANDLE = -11
        handle = kernel32.GetStdHandle(ctypes.wintypes.DWORD(-11 & 0xFFFFFFFF))
        if handle == ctypes.wintypes.HANDLE(-1).value:
            return False

        mode = ctypes.wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False

        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        ENABLE_VTP = 0x0004
        if mode.value & ENABLE_VTP:
            return True  # already enabled

        new_mode = ctypes.wintypes.DWORD(mode.value | ENABLE_VTP)
        if kernel32.SetConsoleMode(handle, new_mode):
            return True

        return False
    except (AttributeError, OSError, ImportError):
        return False


def _is_real_terminal() -> bool:
    """Return ``True`` when stdout is connected to a real terminal.

    Pipes, redirections, and CI environments return ``False``.
    """
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# TerminalManager
# ---------------------------------------------------------------------------

class TerminalManager:
    """Manages the alternate screen buffer for a clean terminal experience.

    On enter:
        - Switches to the alternate screen buffer (preserves the user's
          terminal scrollback).
        - Clears the alternate screen and homes the cursor.

    On exit:
        - Restores the original screen buffer so the user sees their
          previous terminal output, undisturbed.

    On crash / Ctrl+C:
        - Signal handlers for ``SIGINT`` and ``SIGTERM`` ensure the
          alternate screen is left before the process terminates.
        - An :func:`atexit` handler provides an additional safety net.

    When stdout is not a TTY (pipes, CI, redirections) or VT processing
    cannot be enabled (legacy Windows without ``SetConsoleMode`` support),
    every operation degrades silently to a no-op.  The caller never needs
    to handle these cases.
    """

    def __init__(self) -> None:
        self._active: bool = False
        self._vt_supported: bool = False
        self._original_sigint: signal.Handlers | None = None
        self._original_sigterm: signal.Handlers | None = None

    # -- Public API ---------------------------------------------------------

    def enter(self) -> None:
        """Enter the alternate screen buffer."""
        if self._active:
            return

        if not _is_real_terminal():
            return

        self._vt_supported = _enable_windows_vt_processing()
        if not self._vt_supported:
            return

        if not self._write_escape(_ENTER_ALT_SCREEN + _CURSOR_HOME + _CLEAR_SCREEN):
            # Writing failed -- terminal probably doesn't support the
            # escape.  Fall back to doing nothing.
            self._vt_supported = False
            return

        self._active = True
        self._install_signal_handlers()
        atexit.register(self._atexit_handler)

    def exit(self) -> None:
        """Leave the alternate screen buffer and restore the original."""
        if not self._active:
            return

        self._active = False
        self._write_escape(_LEAVE_ALT_SCREEN)
        self._restore_signal_handlers()

        # Remove the atexit handler so it doesn't fire unnecessarily after
        # a clean exit.
        try:
            atexit.unregister(self._atexit_handler)
        except Exception:  # noqa: BLE001
            pass

    def clear(self) -> None:
        """Clear the current (alternate) screen and home the cursor."""
        if self._active and self._vt_supported:
            self._write_escape(_CURSOR_HOME + _CLEAR_SCREEN)

    # -- Context manager protocol -------------------------------------------

    def __enter__(self) -> TerminalManager:
        self.enter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        self.exit()
        return False  # never suppress exceptions

    # -- Signal handling ----------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Install signal handlers that restore the terminal before exit.

        The original handlers are saved so they can be restored later and
        re-raised after cleanup.
        """
        try:
            self._original_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._handle_signal)
        except (OSError, ValueError):
            # signal.signal can fail if not called from the main thread.
            self._original_sigint = None

        # SIGTERM is not available on Windows.
        if hasattr(signal, "SIGTERM"):
            try:
                self._original_sigterm = signal.getsignal(signal.SIGTERM)
                signal.signal(signal.SIGTERM, self._handle_signal)
            except (OSError, ValueError):
                self._original_sigterm = None

    def _restore_signal_handlers(self) -> None:
        """Restore the signal handlers that were active before :meth:`enter`."""
        if self._original_sigint is not None:
            try:
                signal.signal(signal.SIGINT, self._original_sigint)
            except (OSError, ValueError):
                pass
            self._original_sigint = None

        if self._original_sigterm is not None:
            try:
                signal.signal(signal.SIGTERM, self._original_sigterm)
            except (OSError, ValueError):
                pass
            self._original_sigterm = None

    def _handle_signal(self, signum: int, frame: object) -> None:
        """Signal handler: restore the terminal, then re-raise.

        The original handler is invoked after cleanup so callers that
        installed their own handlers (e.g. ``KeyboardInterrupt`` for
        ``SIGINT``) still work as expected.
        """
        self.exit()

        # Determine which original handler to re-invoke.
        original: signal.Handlers | None = None
        if signum == signal.SIGINT:
            original = self._original_sigint
        elif hasattr(signal, "SIGTERM") and signum == signal.SIGTERM:
            original = self._original_sigterm

        if original is not None and callable(original):
            original(signum, frame)
        elif original == signal.SIG_DFL:
            # Re-raise with the default handler.
            signal.signal(signum, signal.SIG_DFL)
            signal.raise_signal(signum)
        else:
            # No original handler -- default behaviour.
            signal.signal(signum, signal.SIG_DFL)
            signal.raise_signal(signum)

    def _atexit_handler(self) -> None:
        """Safety-net: if the process exits without going through
        :meth:`exit`, restore the terminal anyway."""
        self.exit()

    # -- Low-level I/O ------------------------------------------------------

    @staticmethod
    def _write_escape(sequence: str) -> bool:
        """Write an ANSI escape sequence to stdout.

        Returns ``True`` on success, ``False`` if the write fails for any
        reason (broken pipe, closed fd, unsupported terminal, etc.).
        """
        try:
            sys.stdout.write(sequence)
            sys.stdout.flush()
            return True
        except (OSError, ValueError):
            return False
