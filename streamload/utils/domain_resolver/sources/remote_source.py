"""Source that fetches the signed manifest from GitHub raw, with jsDelivr fallback.

Two independent routes to the same upstream content:

    primary  -> https://raw.githubusercontent.com/{repo}/{branch}/{file}
    fallback -> https://cdn.jsdelivr.net/gh/{repo}@{branch}/{file}

The signature file lives next to the manifest as ``<file>.sig``.
"""
from __future__ import annotations

import json
from typing import Any

from streamload.utils.logger import get_logger

from ..errors import ManifestError, SignatureError
from ..models import DomainsManifest
from ..signature import verify_manifest
from .base import DomainSource

log = get_logger(__name__)


class RemoteSource(DomainSource):
    name = "remote"

    def __init__(
        self,
        *,
        http: Any,
        repo: str,
        branch: str,
        manifest_filename: str,
        trusted_keys: dict[str, str],
    ) -> None:
        self._http = http
        self._repo = repo
        self._branch = branch
        self._file = manifest_filename
        self._trusted = trusted_keys
        self._cached: DomainsManifest | None = None
        self._tried = False

    def candidates(self, short_name: str) -> list[str]:
        manifest = self._load()
        if manifest is None:
            return []
        sd = manifest.get_domains(short_name)
        if sd is None:
            return []
        return sd.all_candidates()

    # -- internals --------------------------------------------------------

    def _load(self) -> DomainsManifest | None:
        if self._tried:
            return self._cached
        self._tried = True

        for route, url_body, url_sig in self._routes():
            body = self._fetch(url_body)
            if body is None:
                continue
            sig = self._fetch(url_sig)
            if sig is None:
                continue
            try:
                payload = json.loads(body)
                key_id = payload.get("key_id")
                if not isinstance(key_id, str):
                    raise ManifestError("missing key_id")
                verify_manifest(
                    body.encode("utf-8"),
                    sig.strip(),
                    key_id=key_id,
                    trusted_keys=self._trusted,
                )
                self._cached = DomainsManifest.from_dict(payload)
                log.info("Loaded domains manifest via %s (key_id=%s)", route, key_id)
                return self._cached
            except (json.JSONDecodeError, ManifestError, SignatureError) as exc:
                log.warning("Manifest from %s rejected: %s", route, exc)
                continue
        return None

    def _routes(self) -> list[tuple[str, str, str]]:
        gh_body = f"https://raw.githubusercontent.com/{self._repo}/{self._branch}/{self._file}"
        gh_sig = f"{gh_body}.sig"
        jd_body = f"https://cdn.jsdelivr.net/gh/{self._repo}@{self._branch}/{self._file}"
        jd_sig = f"{jd_body}.sig"
        return [("github", gh_body, gh_sig), ("jsdelivr", jd_body, jd_sig)]

    def _fetch(self, url: str) -> str | None:
        try:
            r = self._http.get(url)
            if getattr(r, "status_code", 0) != 200:
                return None
            return getattr(r, "text", None)
        except Exception:
            log.debug("Remote fetch failed for %s", url, exc_info=True)
            return None
