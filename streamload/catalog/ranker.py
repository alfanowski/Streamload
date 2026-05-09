"""Source ranker.

Combines normalized 0-100 sub-scores into a final score per source. The
top-ranked source is "Server 1", next "Server 2", etc.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# Default weights, sum to 1.0.
DEFAULT_WEIGHTS = {
    "quality": 0.40,
    "latency": 0.20,
    "reliability": 0.20,
    "audio_match": 0.10,
    "subs_match": 0.10,
}


@dataclass
class SourceMetrics:
    service_short_name: str
    service_url: str
    service_media_id: str
    quality_max_height: Optional[int]
    latency_ttfb_ms: Optional[int]
    success_count: int
    failure_count: int
    audio_languages: list[str]
    subtitle_languages: list[str]
    last_verified_at: datetime


@dataclass
class RankedSource:
    label: str
    metrics: SourceMetrics
    score: float


def _quality_score(height: Optional[int]) -> float:
    if height is None:
        return 30.0
    if height >= 2160:
        return 100.0
    if height >= 1080:
        return 100.0
    if height >= 720:
        return 70.0
    if height >= 480:
        return 40.0
    return 20.0


def _latency_score(ms: Optional[int]) -> float:
    if ms is None:
        return 50.0
    if ms <= 500:
        return 100.0
    if ms <= 1500:
        return 70.0
    if ms <= 3000:
        return 40.0
    return 20.0


def _reliability_score(success: int, failure: int) -> float:
    if success + failure == 0:
        return 60.0  # neutral for unverified
    rate = success / (success + failure)
    return rate * 100.0


def _audio_match_score(langs: list[str], pref: Optional[str]) -> float:
    if pref is None:
        return 50.0
    return 100.0 if pref in langs else 50.0


def _subs_match_score(langs: list[str], pref: Optional[str]) -> float:
    if pref is None:
        return 50.0
    return 100.0 if pref in langs else 50.0


def rank_sources(
    sources: list[SourceMetrics],
    *,
    user_audio_pref: Optional[str] = "ita",
    user_subs_pref: Optional[str] = "ita",
    weights: Optional[dict[str, float]] = None,
) -> list[RankedSource]:
    if not sources:
        return []
    w = weights or DEFAULT_WEIGHTS
    ranked: list[tuple[float, SourceMetrics]] = []
    for s in sources:
        score = (
            w["quality"] * _quality_score(s.quality_max_height)
            + w["latency"] * _latency_score(s.latency_ttfb_ms)
            + w["reliability"] * _reliability_score(s.success_count, s.failure_count)
            + w["audio_match"] * _audio_match_score(s.audio_languages, user_audio_pref)
            + w["subs_match"] * _subs_match_score(s.subtitle_languages, user_subs_pref)
        )
        ranked.append((score, s))
    ranked.sort(key=lambda t: t[0], reverse=True)
    return [
        RankedSource(label=f"Server {i+1}", metrics=m, score=round(s, 2))
        for i, (s, m) in enumerate(ranked)
    ]
