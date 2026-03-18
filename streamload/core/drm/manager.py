"""DRM orchestrator that coordinates vault lookups and CDM handlers.

Implements the key resolution chain described in the design spec:

1. Check local vault (SQLite cache).
2. Try remote CDM server (cdrm-project.com).
3. Fallback to local CDM device files (pywidevine / pyplayready).
4. If all fail, raise :class:`DRMError`.

Successful keys are always cached in the vault for future use.

Usage::

    from streamload.core.drm.manager import DRMManager

    manager = DRMManager(config=drm_config, http_client=http, vault=vault)
    keys = manager.get_keys(
        pssh="AAAA...",
        license_url="https://...",
        drm_type="widevine",
        service="cr",
    )
"""

from __future__ import annotations

from streamload.core.drm.playready import PlayReadyCDM
from streamload.core.drm.widevine import WidevineCDM
from streamload.core.exceptions import DRMError
from streamload.core.vault.local import LocalVault
from streamload.models.config import DRMConfig
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

_VALID_DRM_TYPES = frozenset({"widevine", "playready"})


class DRMManager:
    """Orchestrates DRM key acquisition with vault caching.

    Parameters
    ----------
    config:
        DRM subsystem configuration (Widevine + PlayReady device config).
    http_client:
        Shared HTTP client instance.
    vault:
        Local SQLite key vault for caching.
    """

    def __init__(
        self,
        config: DRMConfig,
        http_client: HttpClient,
        vault: LocalVault,
    ) -> None:
        self._config = config
        self._http = http_client
        self._vault = vault
        self._widevine = WidevineCDM(config.widevine, http_client)
        self._playready = PlayReadyCDM(config.playready, http_client)

    # ------------------------------------------------------------------
    # Key resolution chain
    # ------------------------------------------------------------------

    def get_keys(
        self,
        pssh: str,
        license_url: str,
        drm_type: str,
        service: str,
        headers: dict[str, str] | None = None,
    ) -> list[tuple[str, str]]:
        """Get decryption keys using the full resolution chain.

        Resolution order:

        1. **Vault lookup** -- check SQLite cache for the PSSH.
        2. **Remote CDM** -- acquire keys via cdrm-project.com.
        3. **Local CDM** -- fallback to pywidevine/pyplayready if installed.
        4. **Error** -- raise :class:`DRMError` if all sources fail.

        Successfully acquired keys are always cached in the vault
        before being returned.

        Parameters
        ----------
        pssh:
            PSSH box in base64 encoding.
        license_url:
            The streaming service's license server URL.
        drm_type:
            ``"widevine"`` or ``"playready"``.
        service:
            Service short_name (e.g. ``"cr"``), used to tag vault entries.
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
            If all resolution methods fail.
        """
        if drm_type not in _VALID_DRM_TYPES:
            raise DRMError(f"Unsupported DRM type: {drm_type!r}")

        # -- Step 1: Vault cache -------------------------------------------
        keys = self._try_vault(pssh, drm_type)
        if keys:
            return keys

        # -- Step 2: Remote CDM server -------------------------------------
        errors: list[str] = []
        keys = self._try_remote_cdm(pssh, license_url, drm_type, headers, errors)
        if keys:
            self._cache_keys(keys, pssh, drm_type, service)
            return keys

        # -- Step 3: Local CDM fallback ------------------------------------
        keys = self._try_local_cdm(pssh, license_url, drm_type, headers)
        if keys:
            self._cache_keys(keys, pssh, drm_type, service)
            return keys

        # -- Step 4: All methods exhausted ---------------------------------
        error_detail = "; ".join(errors) if errors else "no CDM sources available"
        raise DRMError(
            f"Failed to acquire {drm_type} keys for service={service}: {error_detail}"
        )

    # ------------------------------------------------------------------
    # Resolution steps
    # ------------------------------------------------------------------

    def _try_vault(self, pssh: str, drm_type: str) -> list[tuple[str, str]] | None:
        """Check the local vault for cached keys matching this PSSH.

        Returns ``None`` if no cached keys are found.
        """
        try:
            entries = self._vault.get_keys_by_pssh(pssh)
            # Filter to the requested DRM type.
            matching = [
                (e.kid, e.key) for e in entries if e.drm_type == drm_type
            ]
            if matching:
                log.info(
                    "DRM: vault hit -- %d cached %s key(s) for pssh=%.20s...",
                    len(matching), drm_type, pssh,
                )
                return matching
        except Exception as exc:  # noqa: BLE001
            # Vault errors are non-fatal -- we can still try the CDM.
            log.warning("DRM: vault lookup failed (non-fatal): %s", exc)

        return None

    def _try_remote_cdm(
        self,
        pssh: str,
        license_url: str,
        drm_type: str,
        headers: dict[str, str] | None,
        errors: list[str],
    ) -> list[tuple[str, str]] | None:
        """Attempt key acquisition via the remote CDM server.

        Returns ``None`` on failure and appends the error message
        to *errors* for diagnostic reporting.
        """
        cdm = self._widevine if drm_type == "widevine" else self._playready
        cdm_host = (
            self._config.widevine.host
            if drm_type == "widevine"
            else self._config.playready.host
        )

        if not cdm_host:
            msg = f"Remote {drm_type} CDM host not configured"
            log.debug("DRM: %s", msg)
            errors.append(msg)
            return None

        try:
            log.info("DRM: requesting %s keys from remote CDM (%s)", drm_type, cdm_host)
            keys = cdm.get_keys(pssh, license_url, headers)
            log.info("DRM: remote CDM returned %d key(s)", len(keys))
            return keys
        except DRMError as exc:
            msg = f"Remote CDM failed: {exc.message}"
            log.warning("DRM: %s", msg)
            errors.append(msg)
            return None
        except Exception as exc:  # noqa: BLE001
            msg = f"Remote CDM unexpected error: {exc}"
            log.warning("DRM: %s", msg)
            errors.append(msg)
            return None

    def _try_local_cdm(
        self,
        pssh: str,
        license_url: str,
        drm_type: str,
        headers: dict[str, str] | None = None,
    ) -> list[tuple[str, str]] | None:
        """Try using local pywidevine/pyplayready as a fallback.

        Returns ``None`` if the required library is not installed or if
        key acquisition fails.
        """
        if drm_type == "widevine":
            return self._try_local_widevine(pssh, license_url, headers)
        return self._try_local_playready(pssh, license_url, headers)

    def _try_local_widevine(
        self,
        pssh: str,
        license_url: str,
        headers: dict[str, str] | None,
    ) -> list[tuple[str, str]] | None:
        """Attempt Widevine key acquisition using the local pywidevine library."""
        try:
            from pywidevine.cdm import Cdm  # type: ignore[import-untyped]
            from pywidevine.device import Device  # type: ignore[import-untyped]
            from pywidevine.pssh import PSSH  # type: ignore[import-untyped]
        except ImportError:
            log.debug("DRM: pywidevine not installed -- skipping local CDM fallback")
            return None

        # Search for a .wvd device file in data/
        from pathlib import Path
        device_dir = Path("data")
        wvd_files = list(device_dir.glob("*.wvd")) if device_dir.exists() else []
        if not wvd_files:
            log.debug("DRM: no .wvd device files found in data/ -- skipping local CDM")
            return None

        device_path = wvd_files[0]
        log.info("DRM: attempting local Widevine CDM with device %s", device_path.name)

        try:
            device = Device.load(device_path)
            cdm = Cdm.from_device(device)
            session_id = cdm.open()

            parsed_pssh = PSSH(pssh)
            challenge = cdm.get_license_challenge(session_id, parsed_pssh)

            # Send challenge to license server.
            import base64
            request_headers: dict[str, str] = {"Content-Type": "application/octet-stream"}
            if headers:
                request_headers.update(headers)

            resp = self._http.post(
                license_url,
                headers=request_headers,
                data=challenge,
            )
            if resp.status_code != 200:
                log.warning(
                    "DRM: local Widevine -- license server returned HTTP %d",
                    resp.status_code,
                )
                cdm.close(session_id)
                return None

            cdm.parse_license(session_id, resp.content)

            keys: list[tuple[str, str]] = []
            for key in cdm.get_keys(session_id, "CONTENT"):
                keys.append((key.kid.hex, key.key.hex))

            cdm.close(session_id)

            if keys:
                log.info("DRM: local Widevine CDM returned %d key(s)", len(keys))
                return keys

            log.warning("DRM: local Widevine CDM returned no CONTENT keys")
            return None

        except Exception as exc:  # noqa: BLE001
            log.warning("DRM: local Widevine CDM failed: %s", exc)
            return None

    def _try_local_playready(
        self,
        pssh: str,
        license_url: str,
        headers: dict[str, str] | None,
    ) -> list[tuple[str, str]] | None:
        """Attempt PlayReady key acquisition using the local pyplayready library."""
        try:
            from pyplayready.cdm import Cdm  # type: ignore[import-untyped]
            from pyplayready.device import Device  # type: ignore[import-untyped]
            from pyplayready.pssh import PSSH  # type: ignore[import-untyped]
        except ImportError:
            log.debug("DRM: pyplayready not installed -- skipping local CDM fallback")
            return None

        # Search for a .prd device file in data/
        from pathlib import Path
        device_dir = Path("data")
        prd_files = list(device_dir.glob("*.prd")) if device_dir.exists() else []
        if not prd_files:
            log.debug("DRM: no .prd device files found in data/ -- skipping local CDM")
            return None

        device_path = prd_files[0]
        log.info("DRM: attempting local PlayReady CDM with device %s", device_path.name)

        try:
            device = Device.load(device_path)
            cdm = Cdm.from_device(device)
            session_id = cdm.open()

            parsed_pssh = PSSH(pssh)
            challenge = cdm.get_license_challenge(session_id, parsed_pssh)

            # Send challenge to license server.
            request_headers: dict[str, str] = {"Content-Type": "text/xml"}
            if headers:
                request_headers.update(headers)

            resp = self._http.post(
                license_url,
                headers=request_headers,
                data=challenge,
            )
            if resp.status_code != 200:
                log.warning(
                    "DRM: local PlayReady -- license server returned HTTP %d",
                    resp.status_code,
                )
                cdm.close(session_id)
                return None

            cdm.parse_license(session_id, resp.content)

            keys: list[tuple[str, str]] = []
            for key in cdm.get_keys(session_id):
                kid_hex = key.kid.hex if hasattr(key.kid, "hex") else str(key.kid)
                key_hex = key.key.hex if hasattr(key.key, "hex") else str(key.key)
                keys.append((kid_hex, key_hex))

            cdm.close(session_id)

            if keys:
                log.info("DRM: local PlayReady CDM returned %d key(s)", len(keys))
                return keys

            log.warning("DRM: local PlayReady CDM returned no keys")
            return None

        except Exception as exc:  # noqa: BLE001
            log.warning("DRM: local PlayReady CDM failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Vault caching
    # ------------------------------------------------------------------

    def _cache_keys(
        self,
        keys: list[tuple[str, str]],
        pssh: str,
        drm_type: str,
        service: str,
    ) -> None:
        """Store acquired keys in the vault.

        Vault write failures are logged but never propagated -- losing
        the cache is tolerable, losing the keys is not.
        """
        try:
            self._vault.store_keys(keys, pssh, drm_type, service)
            log.debug(
                "DRM: cached %d key(s) in vault (service=%s, drm_type=%s)",
                len(keys), service, drm_type,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("DRM: failed to cache keys in vault (non-fatal): %s", exc)
