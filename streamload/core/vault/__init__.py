"""Local DRM key vault (SQLite).

Re-exports the public API so callers can import directly from the
package::

    from streamload.core.vault import LocalVault, VaultEntry
"""

from streamload.core.vault.local import LocalVault, VaultEntry

__all__ = [
    "LocalVault",
    "VaultEntry",
]
