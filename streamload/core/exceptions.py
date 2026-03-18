"""Streamload exception hierarchy.

Every exception raised by the core library inherits from
:class:`StreamloadError` so callers can catch a single base type while
still matching on specific failure modes when needed.
"""

from __future__ import annotations


class StreamloadError(Exception):
    """Base exception for all Streamload errors.

    Parameters
    ----------
    message:
        Human-readable description of the problem.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class NetworkError(StreamloadError):
    """A network-level failure: timeout, DNS resolution, or connection error.

    Parameters
    ----------
    message:
        Human-readable description.
    status_code:
        HTTP status code when the failure is an unexpected response,
        or ``None`` for lower-level transport errors.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)

    def __str__(self) -> str:
        if self.status_code is not None:
            return f"{self.message} (HTTP {self.status_code})"
        return self.message


class ServiceError(StreamloadError):
    """A streaming service responded with an error or changed its structure.

    Parameters
    ----------
    message:
        Human-readable description.
    service_name:
        Identifier of the service that failed (e.g. ``"crunchyroll"``).
    """

    def __init__(self, message: str, *, service_name: str) -> None:
        self.service_name = service_name
        super().__init__(message)

    def __str__(self) -> str:
        return f"[{self.service_name}] {self.message}"


class DRMError(StreamloadError):
    """A DRM-related failure: missing key, CDM unavailable, etc."""


class MergeError(StreamloadError):
    """FFmpeg (or another post-processor) failed during muxing/conversion.

    Parameters
    ----------
    message:
        Human-readable description.
    stderr:
        Raw stderr output captured from the process, if available.
    """

    def __init__(self, message: str, *, stderr: str | None = None) -> None:
        self.stderr = stderr
        super().__init__(message)

    def __str__(self) -> str:
        if self.stderr:
            # Show at most the last 5 lines to keep messages readable.
            tail = "\n".join(self.stderr.strip().splitlines()[-5:])
            return f"{self.message}\nFFmpeg output:\n{tail}"
        return self.message


class ConfigError(StreamloadError):
    """Invalid or corrupted configuration.

    Parameters
    ----------
    message:
        Human-readable description.
    field_name:
        Name of the offending config field, if known.
    """

    def __init__(self, message: str, *, field_name: str | None = None) -> None:
        self.field_name = field_name
        super().__init__(message)

    def __str__(self) -> str:
        if self.field_name:
            return f"{self.message} (field: {self.field_name})"
        return self.message


class AuthenticationError(StreamloadError):
    """Credentials are invalid, expired, or missing for a service.

    Parameters
    ----------
    message:
        Human-readable description.
    service_name:
        Identifier of the service whose auth failed.
    """

    def __init__(self, message: str, *, service_name: str) -> None:
        self.service_name = service_name
        super().__init__(message)

    def __str__(self) -> str:
        return f"[{self.service_name}] {self.message}"
