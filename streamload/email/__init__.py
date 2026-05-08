"""Email subsystem (transactional only, Resend backend)."""
from __future__ import annotations

from .client import EmailClient, EmailError

__all__ = ["EmailClient", "EmailError"]
