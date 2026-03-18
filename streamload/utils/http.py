"""Robust HTTP client with retry logic, proxy support, and anti-bot bypass.

Wraps :mod:`httpx` for standard requests and :mod:`curl_cffi` for
Cloudflare-protected endpoints.  Every request method supports automatic
exponential-backoff retries and logs each attempt so failures are
diagnosable from the log file alone.

Usage::

    from streamload.utils.http import HttpClient

    with HttpClient() as http:
        r = http.get("https://example.com/api/video")
        data = r.json()

    # Cloudflare-protected page
    with HttpClient() as http:
        r = http.get("https://protected.site/page", use_curl=True)
"""

from __future__ import annotations

import json as _json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from curl_cffi.requests import Session as CurlSession
from ua_generator import generate as generate_ua

from streamload.core.exceptions import NetworkError
from streamload.models.config import NetworkConfig
from streamload.utils.logger import get_logger

log = get_logger(__name__)

# Default values matching ``NetworkConfig`` defaults so the client works
# without any configuration object at all.
_DEFAULT_TIMEOUT: int = 30
_DEFAULT_MAX_RETRY: int = 8
_DEFAULT_VERIFY_SSL: bool = True
_BACKOFF_BASE: float = 0.5  # seconds; delay = base * 2^attempt


# ---------------------------------------------------------------------------
# Lightweight response wrapper
# ---------------------------------------------------------------------------

@dataclass
class Response:
    """Unified response object returned by every :class:`HttpClient` method.

    Attributes mirror the most-used properties of :class:`httpx.Response` so
    callers don't need to care which backend served the request.
    """

    status_code: int
    text: str
    content: bytes
    headers: dict[str, str]
    url: str

    def json(self) -> Any:
        """Deserialise the response body as JSON.

        Raises :class:`NetworkError` when the body is not valid JSON.
        """
        try:
            return _json.loads(self.text)
        except (ValueError, _json.JSONDecodeError) as exc:
            raise NetworkError(
                f"Failed to decode JSON from {self.url}: {exc}"
            ) from exc

    def raise_for_status(self) -> None:
        """Raise :class:`NetworkError` for 4xx / 5xx status codes."""
        if 400 <= self.status_code < 600:
            raise NetworkError(
                f"HTTP error for {self.url}",
                status_code=self.status_code,
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user_agent() -> str:
    """Generate a realistic desktop browser User-Agent string."""
    ua = generate_ua(device="desktop", browser=("chrome", "firefox", "edge"))
    return str(ua)


def _response_from_httpx(r: httpx.Response) -> Response:
    """Convert an :class:`httpx.Response` into our unified wrapper."""
    return Response(
        status_code=r.status_code,
        text=r.text,
        content=r.content,
        headers=dict(r.headers),
        url=str(r.url),
    )


def _response_from_curl(r: Any) -> Response:
    """Convert a :class:`curl_cffi.requests.Response` into our wrapper."""
    return Response(
        status_code=r.status_code,
        text=r.text,
        content=r.content,
        headers=dict(r.headers),
        url=str(r.url),
    )


def _retriable(exc: BaseException) -> bool:
    """Return ``True`` if *exc* is a transient error worth retrying."""
    # httpx transport errors (DNS, connection reset, timeout, ...)
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    # curl_cffi raises its own exceptions; treat them all as transient
    if type(exc).__module__.startswith("curl_cffi"):
        return True
    # HTTP 429 / 5xx are surfaced via NetworkError after raise_for_status
    if isinstance(exc, NetworkError) and exc.status_code is not None:
        return exc.status_code == 429 or exc.status_code >= 500
    return False


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

class HttpClient:
    """HTTP client with retry logic, proxy support, and anti-bot capabilities.

    Parameters
    ----------
    config:
        A :class:`NetworkConfig` instance.  When ``None`` every setting
        falls back to sensible defaults so the client is usable without
        any configuration file.
    """

    def __init__(self, config: NetworkConfig | None = None) -> None:
        cfg = config or NetworkConfig()

        self._timeout: int = cfg.timeout
        self._max_retry: int = cfg.max_retry
        self._verify_ssl: bool = cfg.verify_ssl
        self._proxy: str | None = cfg.proxy
        self._user_agent: str = _make_user_agent()

        # -- Standard httpx client -----------------------------------------
        transport_kwargs: dict[str, Any] = {}
        if self._proxy:
            transport_kwargs["proxy"] = self._proxy

        self._httpx = httpx.Client(
            timeout=httpx.Timeout(self._timeout, connect=self._timeout),
            verify=self._verify_ssl,
            follow_redirects=True,
            headers={"User-Agent": self._user_agent},
            **transport_kwargs,
        )

        # -- curl_cffi session (Cloudflare / TLS-fingerprint bypass) -------
        self._curl: CurlSession | None = None  # created lazily

    # -- Internal helpers ---------------------------------------------------

    def _get_curl_session(self) -> CurlSession:
        """Lazily create the curl_cffi session."""
        if self._curl is None:
            self._curl = CurlSession(impersonate="chrome")
            self._curl.headers.update({"User-Agent": self._user_agent})
            if self._proxy:
                self._curl.proxies = {
                    "http": self._proxy,
                    "https": self._proxy,
                }
            if not self._verify_ssl:
                self._curl.verify = False
        return self._curl

    def _retry(
        self,
        method: str,
        url: str,
        *,
        use_curl: bool,
        max_retries: int | None,
        request_kwargs: dict[str, Any],
    ) -> Response:
        """Execute a request with exponential-backoff retry.

        Parameters
        ----------
        method:
            HTTP method (``"GET"`` or ``"POST"``).
        url:
            Target URL.
        use_curl:
            When ``True`` route the request through curl_cffi.
        max_retries:
            Override the instance-level retry count for this call.
        request_kwargs:
            Extra keyword arguments forwarded to the underlying client.
        """
        retries = max_retries if max_retries is not None else self._max_retry
        last_exc: BaseException | None = None

        for attempt in range(retries + 1):
            try:
                if use_curl:
                    raw = self._do_curl(method, url, **request_kwargs)
                else:
                    raw = self._do_httpx(method, url, **request_kwargs)

                # Treat server errors as retriable without raising immediately
                if raw.status_code == 429 or raw.status_code >= 500:
                    exc = NetworkError(
                        f"Server returned {raw.status_code} for {url}",
                        status_code=raw.status_code,
                    )
                    if attempt < retries:
                        last_exc = exc
                        self._backoff(attempt, url, exc)
                        continue
                    raise exc

                return raw

            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not _retriable(exc):
                    raise
                if attempt < retries:
                    self._backoff(attempt, url, exc)
                    continue

        # All retries exhausted
        assert last_exc is not None
        if isinstance(last_exc, NetworkError):
            raise last_exc
        raise NetworkError(
            f"Request failed after {retries + 1} attempts: {url} -- {last_exc}"
        ) from last_exc

    def _backoff(self, attempt: int, url: str, exc: BaseException) -> None:
        delay = _BACKOFF_BASE * (2 ** attempt)
        log.warning(
            "Retry %d for %s (%.1fs backoff): %s",
            attempt + 1,
            url,
            delay,
            exc,
        )
        time.sleep(delay)

    def _do_httpx(self, method: str, url: str, **kwargs: Any) -> Response:
        """Issue a request through :mod:`httpx` and return a :class:`Response`."""
        r = self._httpx.request(method, url, **kwargs)
        return _response_from_httpx(r)

    def _do_curl(self, method: str, url: str, **kwargs: Any) -> Response:
        """Issue a request through :mod:`curl_cffi` and return a :class:`Response`."""
        session = self._get_curl_session()
        r = session.request(method, url, timeout=self._timeout, **kwargs)
        return _response_from_curl(r)

    # -- Public API ---------------------------------------------------------

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        use_curl: bool = False,
        max_retries: int | None = None,
    ) -> Response:
        """Send a GET request with automatic retry.

        Parameters
        ----------
        url:
            Target URL.
        headers:
            Extra request headers (merged with defaults).
        params:
            URL query parameters.
        use_curl:
            Route the request through curl_cffi for TLS fingerprint
            impersonation (useful for Cloudflare-protected sites).
        max_retries:
            Override the default retry count for this single call.
        """
        kw: dict[str, Any] = {}
        if headers:
            kw["headers"] = headers
        if params:
            kw["params"] = params
        return self._retry("GET", url, use_curl=use_curl, max_retries=max_retries, request_kwargs=kw)

    def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        use_curl: bool = False,
        max_retries: int | None = None,
    ) -> Response:
        """Send a POST request with automatic retry.

        Parameters
        ----------
        url:
            Target URL.
        headers:
            Extra request headers (merged with defaults).
        data:
            Form-encoded body payload.
        json:
            JSON body payload (mutually exclusive with *data*).
        use_curl:
            Route through curl_cffi for Cloudflare bypass.
        max_retries:
            Override the default retry count for this single call.
        """
        kw: dict[str, Any] = {}
        if headers:
            kw["headers"] = headers
        if data is not None:
            kw["data"] = data
        if json is not None:
            kw["json"] = json
        return self._retry("POST", url, use_curl=use_curl, max_retries=max_retries, request_kwargs=kw)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        """GET a URL and return the parsed JSON body.

        Keyword arguments are forwarded to :meth:`get`.
        """
        resp = self.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def post_json(self, url: str, **kwargs: Any) -> Any:
        """POST to a URL and return the parsed JSON body.

        Keyword arguments are forwarded to :meth:`post`.
        """
        resp = self.post(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def download_file(
        self,
        url: str,
        dest: Path,
        headers: dict[str, str] | None = None,
        chunk_size: int = 8192,
    ) -> Path:
        """Download a file to *dest* using streaming.

        Parameters
        ----------
        url:
            Source URL.
        dest:
            Local file path.  Parent directories are created automatically.
        headers:
            Extra request headers (e.g. ``Range``).
        chunk_size:
            Byte size of each streamed chunk.

        Returns
        -------
        Path
            The resolved destination path.

        Raises
        ------
        NetworkError
            On any transport failure or non-2xx status.
        """
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)

        request_headers: dict[str, str] = {"User-Agent": self._user_agent}
        if headers:
            request_headers.update(headers)

        log.info("Downloading %s -> %s", url, dest)

        try:
            with self._httpx.stream(
                "GET",
                url,
                headers=request_headers,
                follow_redirects=True,
            ) as stream:
                if stream.status_code >= 400:
                    raise NetworkError(
                        f"Download failed for {url}",
                        status_code=stream.status_code,
                    )
                with dest.open("wb") as fp:
                    for chunk in stream.iter_bytes(chunk_size=chunk_size):
                        fp.write(chunk)
        except httpx.TransportError as exc:
            raise NetworkError(f"Download failed for {url}: {exc}") from exc

        log.info("Download complete: %s (%d bytes)", dest, dest.stat().st_size)
        return dest

    # -- Lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Close all underlying sessions and free resources."""
        self._httpx.close()
        if self._curl is not None:
            self._curl.close()
            self._curl = None

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"<HttpClient timeout={self._timeout} retries={self._max_retry} "
            f"proxy={self._proxy!r}>"
        )
