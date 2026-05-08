"""Email subsystem (transactional only, Resend backend)."""
from __future__ import annotations

import os

from .client import EmailClient, EmailError

__all__ = ["EmailClient", "EmailError", "build_email_client"]


def build_email_client() -> EmailClient:
    """Construct an EmailClient from environment.

    Falls back to dry-run mode when ``RESEND_API_KEY`` is not set.
    """
    api_key = os.environ.get("RESEND_API_KEY", "")
    from_addr = os.environ.get("RESEND_FROM", "noreply@resend.dev")
    if not api_key:
        return EmailClient(api_key="", from_address=from_addr, dry_run=True)
    return EmailClient(api_key=api_key, from_address=from_addr)
