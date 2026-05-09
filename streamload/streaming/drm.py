"""DRM segment decryption wrapper.

For DRM-protected content, the v1 ``streamload.core.drm`` module already
extracts content keys via the CDM (Widevine L3 / PlayReady L3). This
module wraps the resulting keys in a callable that decrypts a single
segment's bytes — suitable for use by the ``SegmentFetcher.decryptor``
parameter.

The default ``_decrypt_fn`` calls into ``core.drm.decrypt.decrypt_segment``
(existing). Tests can inject a mock.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


def _real_decrypt(raw: bytes, keys: Any) -> bytes:
    # Import lazily to avoid hard dependency in tests.
    from streamload.core.drm.decrypt import decrypt_segment
    return decrypt_segment(raw, keys=keys)


def build_decryptor(
    *, keys: Optional[Any], _decrypt_fn: Callable[[bytes, Any], bytes] = _real_decrypt,
) -> Optional[Callable[[bytes], bytes]]:
    """Return a callable bytes->bytes that decrypts using *keys*. None if no DRM."""
    if not keys:
        return None
    def decrypt(raw: bytes) -> bytes:
        return _decrypt_fn(raw, keys)
    return decrypt
