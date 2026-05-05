"""Last-resort source that generates candidates by permuting prefix × TLD.

When the signed remote manifest, the local cache, and the hardcoded probe
seeds have all failed, a streaming site has likely rotated to a TLD we've
never seen. This source brute-forces the rotation space by combining each
known prefix (e.g. ``"streamingcommunityz"``) with a curated list of TLDs
known to be popular for streaming domain rotation.

Safety: every candidate emitted here flows through the resolver's active
validator, which only accepts a domain that returns the service's real
Inertia.js shell (``<div id="app" data-page="…version…props…">``). A
malicious squatter who registers ``streamingcommunityz.lol`` cannot pass
the validator unless they also stand up a perfect SC clone — and even
then they cannot bypass the signed-manifest trust path, which always
ranks higher in the source chain.

Cost: each candidate costs one HTTP probe (~1-3s depending on response).
The validator stops at the first match. Worst-case probe count is
``len(prefixes) * len(tlds)`` and is bounded; cache the result for the
configured TTL once a domain validates so subsequent runs are instant.
"""
from __future__ import annotations

from .base import DomainSource


class DiscoverySource(DomainSource):
    """Generates ``<prefix>.<tld>`` permutations for brute-force recovery."""

    name = "discovery"

    def __init__(self, *, seeds: dict[str, dict[str, list[str]]]) -> None:
        # seeds: {short_name: {"prefixes": [...], "tlds": [...]}}
        self._seeds = seeds

    def candidates(self, short_name: str) -> list[str]:
        cfg = self._seeds.get(short_name)
        if not cfg:
            return []
        prefixes = cfg.get("prefixes") or []
        tlds = cfg.get("tlds") or []
        seen: set[str] = set()
        out: list[str] = []
        for prefix in prefixes:
            if not prefix:
                continue
            for tld in tlds:
                if not tld:
                    continue
                domain = f"{prefix}.{tld}"
                if domain not in seen:
                    seen.add(domain)
                    out.append(domain)
        return out
