"""Dataclasses for the domain manifest and resolution results."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import ManifestError

SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (1,)


@dataclass(frozen=True)
class ServiceDomains:
    """Per-service domain list: one primary plus ordered fallbacks."""

    primary: str
    fallbacks: list[str] = field(default_factory=list)

    def all_candidates(self) -> list[str]:
        """Return primary followed by fallbacks, deduped, order preserved."""
        seen: set[str] = set()
        out: list[str] = []
        for d in [self.primary, *self.fallbacks]:
            if d and d not in seen:
                seen.add(d)
                out.append(d)
        return out


@dataclass(frozen=True)
class DomainsManifest:
    """Versioned, signed manifest mapping service short_names to domains.

    Note: ``frozen=True`` prevents reassigning the ``services`` attribute, but
    the underlying dict and ``ServiceDomains.fallbacks`` lists remain mutable.
    Treat instances as read-only after construction.
    """

    schema_version: int
    key_id: str
    issued_at: str
    ttl_seconds: int
    services: dict[str, ServiceDomains]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DomainsManifest":
        required = ("schema_version", "key_id", "issued_at", "ttl_seconds", "services")
        missing = [k for k in required if k not in payload]
        if missing:
            raise ManifestError(f"missing fields: {missing}")

        if payload["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
            raise ManifestError(
                f"unsupported schema_version {payload['schema_version']!r}; "
                f"supported: {SUPPORTED_SCHEMA_VERSIONS}"
            )

        ttl_seconds_int = int(payload["ttl_seconds"])
        if ttl_seconds_int <= 0:
            raise ManifestError(
                f"ttl_seconds must be > 0, got {ttl_seconds_int}"
            )

        services: dict[str, ServiceDomains] = {}
        raw_services = payload["services"]
        if not isinstance(raw_services, dict):
            raise ManifestError("'services' must be an object")
        for short_name, sd in raw_services.items():
            if not isinstance(short_name, str) or not short_name:
                raise ManifestError(f"service short_name must be non-empty string, got {short_name!r}")
            if not isinstance(sd, dict) or "primary" not in sd:
                raise ManifestError(f"service {short_name!r} missing 'primary'")
            services[short_name] = ServiceDomains(
                primary=str(sd["primary"]),
                fallbacks=[str(x) for x in sd.get("fallbacks", [])],
            )

        return cls(
            schema_version=int(payload["schema_version"]),
            key_id=str(payload["key_id"]),
            issued_at=str(payload["issued_at"]),
            ttl_seconds=ttl_seconds_int,
            services=services,
        )

    def get_domains(self, short_name: str) -> ServiceDomains | None:
        return self.services.get(short_name)


@dataclass(frozen=True)
class ResolvedDomain:
    """A successfully resolved + validated domain, with provenance."""

    domain: str
    source: str  # "config" | "cache" | "remote-github" | "remote-jsdelivr" | "probe"
    validated_at: float  # unix epoch
