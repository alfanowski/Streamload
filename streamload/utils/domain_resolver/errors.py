"""Exception types for the domain resolver."""
from __future__ import annotations


class DomainResolutionError(Exception):
    """Raised when no source could produce a validated domain."""


class SignatureError(Exception):
    """Raised when the manifest signature is missing, malformed, or invalid."""


class ManifestError(Exception):
    """Raised when the manifest payload is structurally invalid."""
