"""SQLite-based local DRM key vault for caching decryption keys.

Stores kid:key pairs obtained from CDM servers so repeat downloads of
the same content skip the license acquisition step entirely.  The
database is a single SQLite file (default: ``data/vault.db``) with
WAL journaling for safe concurrent reads.

Usage::

    from streamload.core.vault.local import LocalVault

    with LocalVault() as vault:
        vault.store_key(kid="...", key="...", pssh="...",
                        drm_type="widevine", service="cr")
        entry = vault.get_key("...", "widevine")
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from streamload.utils.logger import get_logger

log = get_logger(__name__)

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS drm_keys (
    id INTEGER PRIMARY KEY,
    pssh TEXT NOT NULL,
    kid TEXT NOT NULL,
    key TEXT NOT NULL,
    drm_type TEXT NOT NULL,
    service TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kid, drm_type)
);
"""

_CREATE_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_drm_keys_pssh ON drm_keys (pssh);
"""


@dataclass(frozen=True)
class VaultEntry:
    """A single cached DRM decryption key."""

    kid: str          # Key ID (hex)
    key: str          # Content key (hex)
    pssh: str         # PSSH box (base64)
    drm_type: str     # "widevine" | "playready"
    service: str      # service short_name
    created_at: str   # ISO timestamp


def _row_to_entry(row: sqlite3.Row) -> VaultEntry:
    """Convert a database row into a :class:`VaultEntry`."""
    return VaultEntry(
        kid=row["kid"],
        key=row["key"],
        pssh=row["pssh"],
        drm_type=row["drm_type"],
        service=row["service"],
        created_at=row["created_at"],
    )


class LocalVault:
    """SQLite-based cache for DRM decryption keys.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  When ``None`` defaults to
        ``data/vault.db`` relative to the current working directory.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path: Path = db_path or Path("data/vault.db")
        self._conn: sqlite3.Connection | None = None
        self._ensure_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_db(self) -> None:
        """Create the database directory, file, and schema if missing."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row

        # WAL mode for concurrent-read safety and better write performance.
        self._conn.execute("PRAGMA journal_mode=WAL;")

        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.execute(_CREATE_INDEX_SQL)
        self._conn.commit()

        log.info("Vault opened: %s", self._db_path)

    def _get_conn(self) -> sqlite3.Connection:
        """Return the active connection, raising if the vault is closed."""
        if self._conn is None:
            raise RuntimeError("Vault is closed")
        return self._conn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_key(self, kid: str, drm_type: str) -> VaultEntry | None:
        """Look up a cached key by KID and DRM type.

        Parameters
        ----------
        kid:
            Key ID in lowercase hex.
        drm_type:
            ``"widevine"`` or ``"playready"``.

        Returns
        -------
        VaultEntry | None
            The cached entry, or ``None`` if no match exists.
        """
        conn = self._get_conn()
        kid_lower = kid.lower()
        row = conn.execute(
            "SELECT kid, key, pssh, drm_type, service, created_at "
            "FROM drm_keys WHERE kid = ? AND drm_type = ?",
            (kid_lower, drm_type),
        ).fetchone()

        if row is None:
            return None

        entry = _row_to_entry(row)
        log.debug("Vault hit: kid=%s drm_type=%s", kid_lower, drm_type)
        return entry

    def get_keys_by_pssh(self, pssh: str) -> list[VaultEntry]:
        """Look up all cached keys for a PSSH box.

        Parameters
        ----------
        pssh:
            PSSH box in base64.

        Returns
        -------
        list[VaultEntry]
            All matching entries (may be empty).
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT kid, key, pssh, drm_type, service, created_at "
            "FROM drm_keys WHERE pssh = ?",
            (pssh,),
        ).fetchall()

        entries = [_row_to_entry(r) for r in rows]
        if entries:
            log.debug("Vault PSSH hit: %d key(s) for pssh=%.20s...", len(entries), pssh)
        return entries

    def store_key(
        self,
        kid: str,
        key: str,
        pssh: str,
        drm_type: str,
        service: str,
    ) -> None:
        """Store a single key in the vault.

        Uses ``INSERT OR REPLACE`` so re-storing the same ``(kid, drm_type)``
        pair updates the existing row rather than failing.

        Parameters
        ----------
        kid:
            Key ID in hex.
        key:
            Content key in hex.
        pssh:
            PSSH box in base64.
        drm_type:
            ``"widevine"`` or ``"playready"``.
        service:
            Service short_name (e.g. ``"cr"``).
        """
        conn = self._get_conn()
        kid_lower = kid.lower()
        key_lower = key.lower()

        conn.execute(
            "INSERT OR REPLACE INTO drm_keys (pssh, kid, key, drm_type, service) "
            "VALUES (?, ?, ?, ?, ?)",
            (pssh, kid_lower, key_lower, drm_type, service),
        )
        conn.commit()
        log.info(
            "Vault store: kid=%s drm_type=%s service=%s",
            kid_lower, drm_type, service,
        )

    def store_keys(
        self,
        keys: list[tuple[str, str]],
        pssh: str,
        drm_type: str,
        service: str,
    ) -> None:
        """Store multiple kid:key pairs at once in a single transaction.

        Parameters
        ----------
        keys:
            List of ``(kid_hex, key_hex)`` tuples.
        pssh:
            PSSH box in base64.
        drm_type:
            ``"widevine"`` or ``"playready"``.
        service:
            Service short_name.
        """
        if not keys:
            return

        conn = self._get_conn()
        rows = [
            (pssh, kid.lower(), key.lower(), drm_type, service)
            for kid, key in keys
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO drm_keys (pssh, kid, key, drm_type, service) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        log.info(
            "Vault batch store: %d key(s), drm_type=%s service=%s",
            len(keys), drm_type, service,
        )

    def count(self) -> int:
        """Return the total number of cached keys."""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM drm_keys").fetchone()
        return int(row[0])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            log.debug("Vault closed: %s", self._db_path)

    def __enter__(self) -> LocalVault:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __repr__(self) -> str:
        count = self.count() if self._conn is not None else "?"
        return f"<LocalVault path={self._db_path} keys={count}>"
