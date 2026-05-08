"""Database package — async SQLAlchemy + models."""
from __future__ import annotations

from .base import Base
from . import models  # noqa: F401  (registers models with Base)
from .session import (
    create_engine,
    create_session_factory,
    get_session,
    init,
    shutdown,
)

__all__ = [
    "Base",
    "models",
    "create_engine",
    "create_session_factory",
    "get_session",
    "init",
    "shutdown",
]
