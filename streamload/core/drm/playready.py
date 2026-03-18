"""PlayReady DRM key acquisition via a remote CDM server.

Implements the full license exchange flow against a pyplayready remote
CDM endpoint (e.g. cdrm-project.com):

1. Open a session on the remote CDM.
2. Generate a license challenge from the content's PSSH box.
3. Send the challenge to the streaming service's license server.
4. Forward the license response back to the CDM to extract keys.
5. Close the session.

Usage::

    from streamload.core.drm.playready import PlayReadyCDM

    cdm = PlayReadyCDM(config=drm_device_config, http_client=http)
    keys = cdm.get_keys(pssh="AAAA...", license_url="https://...")
    # keys → [("kid_hex", "key_hex"), ...]
"""

from __future__ import annotations

import base64

from streamload.core.exceptions import DRMError
from streamload.models.config import DRMDeviceConfig
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)


class PlayReadyCDM:
    """PlayReady DRM key acquisition via remote CDM server.

    Parameters
    ----------
    config:
        Device-level configuration (host, secret, device_name, etc.).
    http_client:
        Shared HTTP client instance for all network requests.
    """

    def __init__(self, config: DRMDeviceConfig, http_client: HttpClient) -> None:
        self._config = config
        self._http = http_client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_url(self, endpoint: str) -> str:
        """Build the full URL for a remote CDM API endpoint."""
        host = self._config.host
        if not host:
            raise DRMError("PlayReady CDM host is not configured")
        return f"{host.rstrip('/')}/{endpoint}"

    def _api_headers(self) -> dict[str, str]:
        """Common headers sent with every remote CDM request."""
        return {"Content-Type": "application/json"}

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _open_session(self) -> str:
        """Open a CDM session on the remote server.

        Returns
        -------
        str
            The session ID assigned by the remote CDM.

        Raises
        ------
        DRMError
            If the server rejects the request.
        """
        payload: dict[str, object] = {
            "device_name": self._config.device_name,
            "secret": self._config.secret,
        }

        log.debug("PlayReady: opening session on %s", self._config.host)
        resp = self._http.post(
            self._api_url("open"),
            json=payload,
            headers=self._api_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

        session_id: str | None = data.get("data", {}).get("session_id") if isinstance(data.get("data"), dict) else None
        if session_id is None:
            session_id = data.get("session_id")

        if not session_id:
            raise DRMError(
                f"PlayReady: failed to open session -- server response: {data}"
            )

        log.debug("PlayReady: session opened: %s", session_id)
        return session_id

    def _get_challenge(self, session_id: str, pssh: str) -> str:
        """Generate a license challenge from the PSSH box.

        Parameters
        ----------
        session_id:
            Active CDM session ID.
        pssh:
            PSSH box encoded as base64.

        Returns
        -------
        str
            License challenge encoded as base64.

        Raises
        ------
        DRMError
            If challenge generation fails.
        """
        payload: dict[str, object] = {
            "session_id": session_id,
            "init_data": pssh,
            "device_name": self._config.device_name,
            "secret": self._config.secret,
        }

        log.debug("PlayReady: generating license challenge")
        resp = self._http.post(
            self._api_url("get_license_challenge"),
            json=payload,
            headers=self._api_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

        challenge: str | None = data.get("data", {}).get("challenge_b64") if isinstance(data.get("data"), dict) else None
        if challenge is None:
            challenge = data.get("challenge_b64")

        if not challenge:
            raise DRMError(
                f"PlayReady: failed to get license challenge -- server response: {data}"
            )

        log.debug("PlayReady: challenge generated (%d chars)", len(challenge))
        return challenge

    def _send_license(
        self,
        challenge: str,
        license_url: str,
        headers: dict[str, str] | None = None,
    ) -> str:
        """Send the license challenge to the streaming service's license server.

        PlayReady license challenges are typically XML-based, so the
        challenge is decoded from base64 and sent as the raw POST body.

        Parameters
        ----------
        challenge:
            License challenge in base64.
        license_url:
            The service's PlayReady license server URL.
        headers:
            Additional headers required by the service (auth tokens,
            cookies, custom headers, etc.).

        Returns
        -------
        str
            License response from the service, encoded as base64.

        Raises
        ------
        DRMError
            If the license server rejects the request.
        """
        challenge_bytes = base64.b64decode(challenge)

        request_headers: dict[str, str] = {"Content-Type": "text/xml"}
        if headers:
            request_headers.update(headers)

        log.debug("PlayReady: sending challenge to license server: %s", license_url)
        resp = self._http.post(
            license_url,
            headers=request_headers,
            data=challenge_bytes,
        )

        if resp.status_code != 200:
            raise DRMError(
                f"PlayReady: license server returned HTTP {resp.status_code} "
                f"for {license_url}"
            )

        license_b64 = base64.b64encode(resp.content).decode("ascii")
        log.debug("PlayReady: license response received (%d bytes)", len(resp.content))
        return license_b64

    def _parse_license(
        self,
        session_id: str,
        license_response: str,
    ) -> list[tuple[str, str]]:
        """Parse the license response to extract decryption keys.

        Parameters
        ----------
        session_id:
            Active CDM session ID.
        license_response:
            License response in base64.

        Returns
        -------
        list[tuple[str, str]]
            List of ``(kid_hex, key_hex)`` tuples.

        Raises
        ------
        DRMError
            If parsing fails or no keys are found.
        """
        payload: dict[str, object] = {
            "session_id": session_id,
            "license_message": license_response,
            "device_name": self._config.device_name,
            "secret": self._config.secret,
        }

        log.debug("PlayReady: parsing license response")
        resp = self._http.post(
            self._api_url("parse_license"),
            json=payload,
            headers=self._api_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract the keys list -- server may nest under "data" or return flat.
        raw_keys: list[dict[str, str]] | None = None
        if isinstance(data.get("data"), dict):
            raw_keys = data["data"].get("keys")
        if raw_keys is None:
            raw_keys = data.get("keys")

        if not raw_keys:
            raise DRMError(
                f"PlayReady: no keys in license response -- server response: {data}"
            )

        keys: list[tuple[str, str]] = []
        for entry in raw_keys:
            kid = entry.get("key_id", "")
            key = entry.get("key", "")
            if kid and key:
                keys.append((kid.lower(), key.lower()))

        if not keys:
            raise DRMError(
                "PlayReady: license response contained entries but no usable keys"
            )

        log.info("PlayReady: obtained %d key(s)", len(keys))
        return keys

    def _close_session(self, session_id: str) -> None:
        """Close a CDM session on the remote server.

        Errors are logged but not propagated -- the session will
        eventually expire on its own.

        Parameters
        ----------
        session_id:
            The session to close.
        """
        payload: dict[str, object] = {
            "session_id": session_id,
            "device_name": self._config.device_name,
            "secret": self._config.secret,
        }

        try:
            resp = self._http.post(
                self._api_url("close"),
                json=payload,
                headers=self._api_headers(),
            )
            resp.raise_for_status()
            log.debug("PlayReady: session closed: %s", session_id)
        except Exception:  # noqa: BLE001
            log.warning("PlayReady: failed to close session %s (non-fatal)", session_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_keys(
        self,
        pssh: str,
        license_url: str,
        headers: dict[str, str] | None = None,
    ) -> list[tuple[str, str]]:
        """Acquire decryption keys for DRM-protected content.

        Executes the complete license exchange flow:

        1. Open CDM session on the remote server.
        2. Generate a license challenge from the PSSH box.
        3. Send the challenge to the service's license server.
        4. Parse the license response via the CDM to extract keys.
        5. Close the session.

        Parameters
        ----------
        pssh:
            PSSH box in base64 encoding.
        license_url:
            The streaming service's PlayReady license server URL.
        headers:
            Additional headers for the license request (auth tokens,
            session cookies, etc.).

        Returns
        -------
        list[tuple[str, str]]
            List of ``(kid_hex, key_hex)`` tuples.

        Raises
        ------
        DRMError
            If any step of the flow fails.
        """
        if not self._config.host:
            raise DRMError("PlayReady: remote CDM host is not configured")

        session_id: str | None = None
        try:
            session_id = self._open_session()
            challenge = self._get_challenge(session_id, pssh)
            license_response = self._send_license(challenge, license_url, headers)
            keys = self._parse_license(session_id, license_response)
            return keys
        except DRMError:
            raise
        except Exception as exc:
            raise DRMError(f"PlayReady: unexpected error during key acquisition: {exc}") from exc
        finally:
            if session_id is not None:
                self._close_session(session_id)
