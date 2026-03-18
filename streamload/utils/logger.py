"""Structured file logging with rotation for Streamload.

All log output goes to a rotating file.  Nothing is printed to the
console -- the CLI layer is solely responsible for user-facing output.

Usage::

    from streamload.utils.logger import get_logger, setup_logging

    setup_logging()                       # call once at startup
    log = get_logger(__name__)            # per-module logger
    log.info("Download started: %s", url)
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_ROOT_LOGGER_NAME = "streamload"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 3
_DEFAULT_LOG_FILENAME = "streamload.log"

_initialized: bool = False


def setup_logging(
    log_dir: Path | None = None,
    debug: bool = False,
) -> None:
    """Configure the root ``streamload`` logger.

    This should be called **once** during application startup.  Repeated
    calls are silently ignored so that tests or plugin code that import
    Streamload don't accidentally reconfigure logging.

    Parameters
    ----------
    log_dir:
        Directory where ``streamload.log`` will be written.  Defaults to
        the current working directory (project root when launched via the
        CLI entry-point).
    debug:
        When ``True`` the file handler level is lowered to ``DEBUG``.
    """
    global _initialized  # noqa: PLW0603
    if _initialized:
        return
    _initialized = True

    resolved_dir = Path(log_dir) if log_dir is not None else Path.cwd()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    log_file = resolved_dir / _DEFAULT_LOG_FILENAME

    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(logging.DEBUG)  # let handlers decide their own threshold

    # -- Rotating file handler (always present) ----------------------------
    file_handler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(file_handler)

    # -- Ensure any pre-existing console handlers respect WARNING ----------
    # Libraries or test harnesses may attach a StreamHandler before us.
    # We clamp them to WARNING so the CLI layer stays in control.
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, RotatingFileHandler
        ):
            handler.setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``streamload`` namespace.

    If *name* already starts with ``streamload.`` it is used as-is;
    otherwise it is prefixed automatically.

    Parameters
    ----------
    name:
        Logger name, typically ``__name__`` of the calling module.
    """
    if not name.startswith(f"{_ROOT_LOGGER_NAME}."):
        name = f"{_ROOT_LOGGER_NAME}.{name}"
    return logging.getLogger(name)
