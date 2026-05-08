"""Resend email client wrapper."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from streamload.email.client import EmailClient, EmailError


@pytest.mark.asyncio
async def test_send_calls_resend_api(monkeypatch):
    fake_resp = {"id": "fake-msg-id"}
    fake_send = MagicMock(return_value=fake_resp)
    monkeypatch.setattr("streamload.email.client.resend.Emails.send", fake_send)

    client = EmailClient(api_key="re_fake", from_address="noreply@example.com")
    msg_id = await client.send(
        to="user@example.com",
        subject="hi",
        html="<p>hi</p>",
        text="hi",
    )
    assert msg_id == "fake-msg-id"
    fake_send.assert_called_once()
    args = fake_send.call_args[0][0]
    assert args["to"] == ["user@example.com"]
    assert args["subject"] == "hi"


@pytest.mark.asyncio
async def test_send_raises_on_resend_error(monkeypatch):
    def boom(_):
        raise RuntimeError("resend down")
    monkeypatch.setattr("streamload.email.client.resend.Emails.send", boom)

    client = EmailClient(api_key="re_fake", from_address="noreply@example.com")
    with pytest.raises(EmailError):
        await client.send(to="x@x", subject="x", html="x", text="x")


@pytest.mark.asyncio
async def test_send_in_dry_run_mode_does_not_call_api(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr("streamload.email.client.resend.Emails.send", fake_send)

    client = EmailClient(api_key="", from_address="noreply@example.com", dry_run=True)
    msg_id = await client.send(to="x@x", subject="x", html="x", text="x")
    assert msg_id.startswith("dry-run-")
    fake_send.assert_not_called()
