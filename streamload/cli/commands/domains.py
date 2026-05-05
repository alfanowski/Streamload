"""CLI handlers for the domains subcommand."""
from __future__ import annotations

from datetime import datetime, timezone

from streamload.utils.domain_resolver.cache import DomainCache


def cmd_status(*, cache: DomainCache) -> None:
    entries = cache.entries()
    if not entries:
        print("no cached domains")
        return
    print(f"{'service':10} {'domain':40} {'source':18} {'validated_at'}")
    for short_name, e in sorted(entries.items()):
        ts = datetime.fromtimestamp(e.get("validated_at", 0), tz=timezone.utc).isoformat()
        print(f"{short_name:10} {e.get('domain',''):40} {e.get('source',''):18} {ts}")


def cmd_refresh(*, cache: DomainCache, short_name: str | None) -> None:
    if short_name:
        cache.invalidate(short_name)
        print(f"invalidated {short_name}")
        return
    for sn in list(cache.entries().keys()):
        cache.invalidate(sn)
    print("invalidated all")


def cmd_pin(*, config: dict, short_name: str, url: str) -> None:
    config.setdefault("services", {}).setdefault(short_name, {})["base_url"] = url
    print(f"pinned {short_name} -> {url}")
