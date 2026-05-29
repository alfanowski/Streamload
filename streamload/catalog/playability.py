"""Catalog playability ranking — pure scoring, no IO.

Soft-priority: we never hide titles, we sort the plugin-playable-likely ones
to the top of each row. The heuristic is a cold-start prior using only fields
already present in the TMDB discover/trending payload (no extra round-trips).
A crowd-sourced score (Phase 2) layers on top of this.

See docs/superpowers/specs/2026-05-29-catalog-playability-curation-design.md
"""
from __future__ import annotations

import math

from streamload.catalog.tmdb import TmdbItem

# Countries the Italian plugins (sc / au / rai) actually cover, mirroring
# tmdb._WESTERN_COUNTRIES. Kept as a set here for O(1) membership.
_WESTERN = {
    "US", "GB", "IT", "FR", "ES", "DE", "CA", "AU", "IE",
    "NL", "BE", "SE", "NO", "DK", "FI", "PT", "CH", "AT", "NZ",
}
_PREFERRED_LANGS = {"it", "en"}

# Weights sum to 100. Documented in the spec § "Heuristic scorer".
_W_ORIGIN = 40.0
_W_LANG = 20.0
_W_VOTES = 20.0
_W_POPULARITY = 12.0
_W_RECENCY = 8.0

# Caps so a single runaway field can't dominate the log-scaled terms.
_VOTE_CAP = 5000.0
_POPULARITY_CAP = 200.0
_RECENCY_YEARS = 3
# Current-ish year baseline for recency. Titles only need "recent relative to
# now"; bump this constant at release time if it drifts.
_NOW_YEAR = 2026


def heuristic_score(item: TmdbItem, *, is_anime_row: bool = False) -> float:
    """0..100 prior that the IT plugins can play this title.

    ``is_anime_row`` flips the origin preference: anime rows reward JP origin,
    normal rows reward Western origin (matching the discover Western filter).
    """
    score = 0.0

    # Origin (40)
    countries = set(item.origin_country or [])
    if is_anime_row:
        if "JP" in countries:
            score += _W_ORIGIN
    else:
        if countries & _WESTERN:
            score += _W_ORIGIN

    # Language (20)
    lang = (item.original_language or "").lower()
    if is_anime_row:
        if lang == "ja":
            score += _W_LANG
    else:
        if lang in _PREFERRED_LANGS:
            score += _W_LANG

    # Votes (20) — log-scaled, capped.
    votes = min(float(item.vote_count or 0), _VOTE_CAP)
    if votes > 0:
        score += _W_VOTES * (math.log1p(votes) / math.log1p(_VOTE_CAP))

    # Popularity (12) — normalized, capped.
    pop = min(float(item.popularity or 0.0), _POPULARITY_CAP)
    if pop > 0:
        score += _W_POPULARITY * (pop / _POPULARITY_CAP)

    # Recency (8) — released within the last _RECENCY_YEARS.
    if item.year and (_NOW_YEAR - item.year) <= _RECENCY_YEARS and item.year <= _NOW_YEAR + 1:
        score += _W_RECENCY

    return max(0.0, min(100.0, score))
