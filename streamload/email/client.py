"""Resend email client (async wrapper).

The official ``resend`` SDK is sync; we wrap calls in ``asyncio.to_thread``
to avoid blocking the event loop.

Set ``dry_run=True`` (or pass an empty api_key) to no-op the send during
local development. The returned message ID will be prefixed ``dry-run-``.
"""
from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass

import resend

from streamload.utils.logger import get_logger

log = get_logger(__name__)


class EmailError(Exception):
    """Raised when Resend rejects the message."""


@dataclass
class EmailClient:
    api_key: str
    from_address: str
    dry_run: bool = False

    def __post_init__(self) -> None:
        if not self.dry_run and not self.api_key:
            self.dry_run = True
            log.warning("EmailClient has no api_key; falling back to dry-run mode")
        if self.api_key:
            resend.api_key = self.api_key

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
    ) -> str:
        """Send an email. Returns the Resend message ID."""
        if self.dry_run:
            msg_id = f"dry-run-{secrets.token_hex(8)}"
            log.info("DRY-RUN email to=%s subject=%s id=%s", to, subject, msg_id)
            return msg_id
        payload = {
            "from": self.from_address,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        }
        try:
            resp = await asyncio.to_thread(resend.Emails.send, payload)
        except Exception as exc:
            log.error("Resend send failed: %s", exc, exc_info=True)
            raise EmailError(f"resend error: {exc}") from exc
        msg_id = resp.get("id", "") if isinstance(resp, dict) else ""
        if not msg_id:
            raise EmailError(f"resend returned unexpected response: {resp!r}")
        log.info("Sent email to=%s subject=%s id=%s", to, subject, msg_id)
        return msg_id
