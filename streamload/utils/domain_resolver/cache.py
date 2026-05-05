"""Atomic, lock-protected JSON cache for resolved domains.

Schema:
    {
      "version": 1,
      "entries": {
        "<short_name>": {
          "domain": "x.tld",
          "source": "remote-github",
          "validated_at": 1714912345.0
        }
      }
    }
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    import fcntl  # type: ignore[import-not-found]
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover -- Windows
    _HAS_FCNTL = False


_SCHEMA_VERSION = 1


class DomainCache:
    """File-backed cache of resolved domains, safe across processes."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    # -- Read API ----------------------------------------------------------

    def get(self, short_name: str) -> dict[str, Any] | None:
        data = self._read()
        return data.get("entries", {}).get(short_name)

    def entries(self) -> dict[str, dict[str, Any]]:
        """Return all cached entries as a copy (safe to iterate without locking)."""
        return dict(self._read().get("entries", {}))

    def is_fresh(self, short_name: str, *, ttl_seconds: int, now: float | None = None) -> bool:
        entry = self.get(short_name)
        if entry is None:
            return False
        ts = float(entry.get("validated_at", 0))
        return ((now if now is not None else time.time()) - ts) < ttl_seconds

    # -- Write API ---------------------------------------------------------

    def set(self, short_name: str, *, domain: str, source: str, validated_at: float) -> None:
        def mutate(data: dict[str, Any]) -> dict[str, Any]:
            data.setdefault("entries", {})[short_name] = {
                "domain": domain,
                "source": source,
                "validated_at": validated_at,
            }
            return data

        self._mutate(mutate)

    def invalidate(self, short_name: str) -> None:
        def mutate(data: dict[str, Any]) -> dict[str, Any]:
            entries = data.get("entries", {})
            entries.pop(short_name, None)
            data["entries"] = entries
            return data

        self._mutate(mutate)

    # -- Internals ---------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": _SCHEMA_VERSION, "entries": {}}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Corrupt JSON -> treat as empty so a fresh write overwrites it.
            # OSError (permission denied, I/O error) deliberately not caught:
            # we'd rather surface the real failure than silently overwrite.
            return {"version": _SCHEMA_VERSION, "entries": {}}

    def _mutate(self, fn) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        with open(lock_path, "w") as lock_fh:
            if _HAS_FCNTL:
                fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                data = self._read()
                data = fn(data)
                self._atomic_write(data)
            finally:
                if _HAS_FCNTL:
                    fcntl.flock(lock_fh, fcntl.LOCK_UN)

    def _atomic_write(self, data: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(prefix=".cache-", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
