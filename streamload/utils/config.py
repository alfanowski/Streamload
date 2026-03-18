"""Configuration manager for Streamload.

Loads, validates, and persists ``config.json`` (application settings) and
``login.json`` (service credentials / TMDB API key).

Resilient by design -- a missing or corrupt file never crashes the
application.  Defaults are applied silently and the user is notified via
the log file.

Usage::

    from streamload.utils.config import ConfigManager

    cfg = ConfigManager()
    print(cfg.config.download.thread_count)  # lazy-loads on first access
    print(cfg.get_tmdb_api_key())
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from streamload.models.config import (
    AppConfig,
    DRMConfig,
    DRMDeviceConfig,
    DownloadConfig,
    NetworkConfig,
    OutputConfig,
    ProcessConfig,
)
from streamload.utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Default login.json structure
# ---------------------------------------------------------------------------

_DEFAULT_LOGIN: dict[str, Any] = {
    "TMDB": {
        "api_key": "",
    },
    "SERVICES": {},
}


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """Loads, validates, and manages application configuration.

    Parameters
    ----------
    config_path:
        Path to ``config.json``.  Defaults to ``config.json`` in the
        current working directory (project root when started via the CLI).
    login_path:
        Path to ``login.json``.  Same default logic.
    """

    def __init__(
        self,
        config_path: Path | None = None,
        login_path: Path | None = None,
    ) -> None:
        self._config_path: Path = config_path or Path("config.json")
        self._login_path: Path = login_path or Path("login.json")
        self._config: AppConfig | None = None
        self._login: dict[str, Any] | None = None

    # -- Public properties --------------------------------------------------

    @property
    def config(self) -> AppConfig:
        """Return the current application config.

        The file is loaded lazily on first access.  Subsequent reads
        return the cached instance -- call :meth:`reload` to re-read
        from disk.
        """
        if self._config is None:
            self._config = self.load_config()
        return self._config

    @property
    def login(self) -> dict[str, Any]:
        """Return the current login data.

        Loaded lazily on first access, cached afterwards.
        """
        if self._login is None:
            self._login = self.load_login()
        return self._login

    @property
    def config_path(self) -> Path:
        """Resolved path to the config file."""
        return self._config_path

    @property
    def login_path(self) -> Path:
        """Resolved path to the login file."""
        return self._login_path

    # -- Loading ------------------------------------------------------------

    def load_config(self) -> AppConfig:
        """Load ``config.json``, validate, and apply defaults for missing fields.

        If the file does not exist it is created with default values.  If
        the file contains malformed JSON, a warning is logged and an
        all-defaults config is returned.
        """
        if not self._config_path.exists():
            log.info("config.json not found at %s -- creating with defaults", self._config_path)
            config = AppConfig()
            self._config = config
            self.save_config(config)
            return config

        raw_text: str = ""
        try:
            raw_text = self._config_path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("Could not read %s: %s -- using defaults", self._config_path, exc)
            return AppConfig()

        if not raw_text.strip():
            log.warning("config.json is empty -- using defaults")
            config = AppConfig()
            self._config = config
            self.save_config(config)
            return config

        try:
            data = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning(
                "Malformed JSON in %s: %s -- using defaults",
                self._config_path,
                exc,
            )
            return AppConfig()

        config = AppConfig.from_dict(data)

        # Persist back so that any fields that were added in a newer version
        # of Streamload (or corrected from invalid values) appear on disk.
        self._config = config
        self._save_json(self._config_path, config.to_dict())

        return config

    def load_login(self) -> dict[str, Any]:
        """Load ``login.json``.

        Returns the default empty structure when the file is missing or
        unreadable.  If neither ``login.json`` nor ``login.json.example``
        exists, the example file is created as a template.
        """
        if not self._login_path.exists():
            log.info("login.json not found at %s", self._login_path)
            self._maybe_create_login_example()
            return _deep_copy_login_default()

        try:
            raw_text = self._login_path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("Could not read %s: %s -- using empty login", self._login_path, exc)
            return _deep_copy_login_default()

        if not raw_text.strip():
            log.warning("login.json is empty -- using defaults")
            return _deep_copy_login_default()

        try:
            data = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning(
                "Malformed JSON in %s: %s -- using empty login",
                self._login_path,
                exc,
            )
            return _deep_copy_login_default()

        if not isinstance(data, dict):
            log.warning(
                "login.json root must be a JSON object, got %s -- using empty login",
                type(data).__name__,
            )
            return _deep_copy_login_default()

        # Ensure the expected top-level keys exist.
        data.setdefault("TMDB", {"api_key": ""})
        data.setdefault("SERVICES", {})
        return data

    # -- Saving -------------------------------------------------------------

    def save_config(self, config: AppConfig | None = None) -> None:
        """Save the application config to disk as pretty-printed JSON.

        Parameters
        ----------
        config:
            Configuration to save.  When ``None`` the currently cached
            config is used.
        """
        target = config or self._config
        if target is None:
            log.warning("save_config called with no config to save")
            return
        self._config = target
        self._save_json(self._config_path, target.to_dict())

    # -- Credential helpers -------------------------------------------------

    def get_service_credentials(self, service_name: str) -> dict[str, Any] | None:
        """Return the credentials dict for *service_name*, or ``None``.

        Service names are matched case-insensitively against keys in
        ``login.json["SERVICES"]``.
        """
        services: dict[str, Any] = self.login.get("SERVICES", {})
        if not isinstance(services, dict):
            return None

        # Exact match first.
        if service_name in services:
            value = services[service_name]
            return value if isinstance(value, dict) else None

        # Case-insensitive fallback.
        lower_name = service_name.lower()
        for key, value in services.items():
            if key.lower() == lower_name and isinstance(value, dict):
                return value
        return None

    def get_tmdb_api_key(self) -> str | None:
        """Return the TMDB API key, or ``None`` if not configured."""
        tmdb: Any = self.login.get("TMDB")
        if not isinstance(tmdb, dict):
            return None
        api_key = tmdb.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
        return None

    # -- Defaults creation --------------------------------------------------

    def create_default_config(self) -> None:
        """Create ``config.json`` with all default values."""
        config = AppConfig()
        self._config = config
        self._save_json(self._config_path, config.to_dict())
        log.info("Created default config.json at %s", self._config_path)

    def create_default_login(self) -> None:
        """Create ``login.json.example`` with the empty template structure.

        The example file (not ``login.json`` itself) is written so that
        real credentials are never accidentally generated by the
        application.
        """
        example_path = self._login_path.with_suffix(".json.example")
        self._save_json(example_path, _deep_copy_login_default())
        log.info("Created login.json.example at %s", example_path)

    # -- Reloading ----------------------------------------------------------

    def reload(self) -> None:
        """Discard cached data and reload both files from disk."""
        self._config = None
        self._login = None
        log.info("Configuration cache cleared -- next access will reload from disk")

    def reload_config(self) -> AppConfig:
        """Force-reload ``config.json`` from disk and return the result."""
        self._config = None
        return self.config

    def reload_login(self) -> dict[str, Any]:
        """Force-reload ``login.json`` from disk and return the result."""
        self._login = None
        return self.login

    # -- Internal -----------------------------------------------------------

    def _maybe_create_login_example(self) -> None:
        """Create ``login.json.example`` if neither it nor ``login.json`` exists."""
        example_path = self._login_path.with_suffix(".json.example")
        if example_path.exists():
            return
        self.create_default_login()

    @staticmethod
    def _save_json(path: Path, data: dict[str, Any]) -> None:
        """Atomically write *data* as pretty-printed JSON to *path*.

        Writes to a temporary sibling file first, then replaces the
        target -- this avoids leaving a half-written file on disk if the
        process is killed mid-write.
        """
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(data, indent=4, ensure_ascii=False) + "\n"
            tmp_path.write_text(content, encoding="utf-8")
            tmp_path.replace(path)
        except OSError as exc:
            log.error("Failed to write %s: %s", path, exc)
            # Clean up the temp file on failure.
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------

def _deep_copy_login_default() -> dict[str, Any]:
    """Return a fresh deep copy of the default login structure.

    Using a function instead of ``copy.deepcopy`` avoids pulling in the
    :mod:`copy` module for a trivially small nested dict.
    """
    return {
        "TMDB": {
            "api_key": "",
        },
        "SERVICES": {},
    }
