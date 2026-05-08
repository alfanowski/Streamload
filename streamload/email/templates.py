"""Email templates: HTML + plain-text bodies for transactional emails."""
from __future__ import annotations

_BRAND_COLOR = "#d4a574"

_BASE_HTML = """\
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
</head>
<body style="margin:0;padding:24px;background:#0a0a0a;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
    <table role="presentation" style="max-width:520px;margin:0 auto;background:#141414;border-radius:12px;overflow:hidden;">
        <tr><td style="padding:32px 28px;">
            <h1 style="margin:0 0 16px;font-size:24px;font-weight:700;letter-spacing:-0.5px;">{heading}</h1>
            <div style="font-size:15px;line-height:1.5;color:rgba(255,255,255,0.85);">{body_html}</div>
            <div style="margin-top:24px;text-align:center;">
                <a href="{cta_url}" style="display:inline-block;padding:14px 28px;background:{accent};color:#1a1410;text-decoration:none;border-radius:24px;font-weight:600;font-size:14px;">{cta_text}</a>
            </div>
            <div style="margin-top:32px;font-size:12px;color:rgba(255,255,255,0.4);line-height:1.4;">
                Se non hai richiesto questa email, ignorala — il link scadr&agrave; tra {ttl}.
            </div>
        </td></tr>
    </table>
</body>
</html>
"""


def verification_email(*, username: str, link: str, ttl_label: str = "24 ore") -> tuple[str, str, str]:
    subject = "Conferma il tuo account Streamload"
    html = _BASE_HTML.format(
        title=subject,
        heading=f"Ciao {username}!",
        body_html=(
            "Per completare la registrazione su Streamload, clicca il pulsante "
            "qui sotto per confermare il tuo indirizzo email."
        ),
        cta_url=link,
        cta_text="Conferma email",
        accent=_BRAND_COLOR,
        ttl=ttl_label,
    )
    text = (
        f"Ciao {username}!\n\n"
        f"Per completare la registrazione su Streamload, apri questo link:\n{link}\n\n"
        f"Il link scade tra {ttl_label}. Se non hai richiesto questa email, ignorala.\n"
    )
    return subject, html, text


def password_reset_email(*, username: str, link: str, ttl_label: str = "1 ora") -> tuple[str, str, str]:
    subject = "Reimposta la tua password Streamload"
    html = _BASE_HTML.format(
        title=subject,
        heading=f"Ciao {username},",
        body_html=(
            "Hai richiesto di reimpostare la password. Clicca il pulsante per "
            "scegliere una nuova password. Per sicurezza, tutte le tue sessioni "
            "attive verranno terminate al cambio password."
        ),
        cta_url=link,
        cta_text="Reimposta password",
        accent=_BRAND_COLOR,
        ttl=ttl_label,
    )
    text = (
        f"Ciao {username},\n\n"
        f"Hai richiesto di reimpostare la password. Apri questo link:\n{link}\n\n"
        f"Il link scade tra {ttl_label}. Se non hai richiesto questa email, ignorala.\n"
    )
    return subject, html, text
