"""Internationalisation support for the Streamload CLI.

Usage::

    from streamload.cli.i18n import I18n

    i18n = I18n()          # auto-detect system language
    i18n = I18n("it")      # force Italian
    print(i18n.t("menu.welcome"))
    print(i18n.t("download.progress", name="Movie", pct=42))
"""

from __future__ import annotations

import locale
import logging
from typing import Any

log = logging.getLogger(__name__)

# Supported language codes and their string modules.
_SUPPORTED_LANGS = ("en", "it")
_DEFAULT_LANG = "en"


def _detect_system_language() -> str:
    """Return ``"it"`` if the system locale looks Italian, else ``"en"``."""
    code: str | None = None

    try:
        raw = locale.getlocale()
        code = raw[0] if raw and raw[0] else None
    except (ValueError, AttributeError):
        pass

    # Fallback to the deprecated-but-reliable getdefaultlocale().
    if code is None:
        try:
            raw = locale.getdefaultlocale()  # type: ignore[attr-defined]
            code = raw[0] if raw and raw[0] else None
        except (ValueError, AttributeError):
            pass

    if code is not None and code.lower().startswith("it"):
        return "it"
    return "en"


def _load_strings(lang: str) -> dict[str, str]:
    """Import and return the string table for *lang*."""
    if lang == "it":
        from streamload.cli.i18n.it import STRINGS
    else:
        from streamload.cli.i18n.en import STRINGS
    return STRINGS


class I18n:
    """Lightweight internationalisation helper.

    Parameters
    ----------
    lang:
        Language code (``"it"``, ``"en"``) or ``"auto"`` (default) to
        detect the system locale.
    """

    __slots__ = ("_lang", "_strings")

    def __init__(self, lang: str = "auto") -> None:
        if lang == "auto":
            resolved = _detect_system_language()
        elif lang in _SUPPORTED_LANGS:
            resolved = lang
        else:
            log.warning("i18n: unsupported language %r -- falling back to %r", lang, _DEFAULT_LANG)
            resolved = _DEFAULT_LANG

        self._lang: str = resolved
        self._strings: dict[str, str] = _load_strings(resolved)
        log.debug("i18n: loaded %d strings for %r", len(self._strings), resolved)

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def lang(self) -> str:
        """Current language code (``"it"`` or ``"en"``)."""
        return self._lang

    def get_lang(self) -> str:
        """Return the current language code."""
        return self._lang

    def t(self, key: str, **kwargs: Any) -> str:
        """Translate *key*, interpolating ``{param}`` placeholders.

        Returns the key itself when no translation is found so the
        application never crashes from a missing string.
        """
        template = self._strings.get(key)
        if template is None:
            log.warning("i18n: missing key %r for lang %r", key, self._lang)
            return key

        if kwargs:
            try:
                return template.format(**kwargs)
            except KeyError as exc:
                log.warning("i18n: missing placeholder %s in key %r", exc, key)
                return template
        return template

    # ── Language-aware preference helpers ──────────────────────────────────

    def get_audio_preferences(self) -> str:
        """Return pipe-separated audio language codes for track selection.

        Italian: ``"ita|it"``  --  English: ``"eng|en"``
        """
        if self._lang == "it":
            return "ita|it"
        return "eng|en"

    def get_subtitle_preferences(self) -> str:
        """Return pipe-separated subtitle language codes for track selection.

        Italian: ``"ita|it"``  --  English: ``"eng|en"``
        """
        if self._lang == "it":
            return "ita|it"
        return "eng|en"

    # ── Dunder helpers ────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"I18n(lang={self._lang!r}, keys={len(self._strings)})"
