"""Title normalization + fuzzy matching using rapidfuzz.

Normalization strips:
- leading articles ("the", "il", "la", "le", "lo", "les", "el")
- year in parentheses
- diacritics
- punctuation
- excess whitespace

Match score combines title fuzzy similarity (rapidfuzz token_set_ratio)
with optional year proximity (±1 year accepted, larger penalty beyond).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional, Protocol, TypeVar

from rapidfuzz import fuzz

_LEADING_ARTICLES = {
    "the", "a", "an",
    "il", "la", "le", "lo", "li", "gli", "i",
    "el", "los", "las",
    "le", "les", "la", "l'",
    "de",
}

_YEAR_RE = re.compile(r"\(\d{4}\)")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_title(title: str) -> str:
    """Lowercase, strip articles, year, diacritics, punctuation."""
    s = title.strip().lower()
    s = _YEAR_RE.sub("", s)
    # Strip diacritics (è -> e)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # Strip punctuation
    s = _PUNCT_RE.sub(" ", s)
    # Drop leading article if any
    parts = s.split()
    while parts and parts[0] in _LEADING_ARTICLES:
        parts = parts[1:]
    return " ".join(parts).strip()


def title_similarity(a: str, b: str) -> int:
    """0-100 similarity score using token_set_ratio (order-insensitive)."""
    return int(fuzz.token_set_ratio(normalize_title(a), normalize_title(b)))


class _Candidate(Protocol):
    title: str
    year: Optional[int]


T = TypeVar("T", bound=_Candidate)


def best_match(
    candidates: Iterable[T],
    *,
    target_title: str,
    target_year: Optional[int] = None,
    min_score: int = 88,
) -> Optional[T]:
    """Pick the candidate with the highest combined score.

    The score is title similarity (0-100) minus a penalty for year drift:
    - same year: 0
    - ±1 year: -5
    - ±2 years: -15
    - more: -30 (still possible to win if title is uniquely strong)

    Returns ``None`` when no candidate scores >= ``min_score`` (after penalty).

    Default ``min_score=88`` is tuned so that:
    - exact title (sim 100) and "X" vs "X Subtitle" (token-set sim 100) pass
    - single-character or single-token differences ("Movie A" vs "Movie B",
      both score ~86 via token_set_ratio) are rejected as ambiguous
    """
    best: tuple[Optional[T], int] = (None, -1)
    for c in candidates:
        sim = title_similarity(target_title, c.title)
        penalty = 0
        if target_year is not None and c.year is not None:
            d = abs(target_year - c.year)
            if d == 1:
                penalty = 5
            elif d == 2:
                penalty = 15
            elif d > 2:
                penalty = 30
        score = sim - penalty
        if score > best[1]:
            best = (c, score)
    if best[0] is None or best[1] < min_score:
        return None
    return best[0]
