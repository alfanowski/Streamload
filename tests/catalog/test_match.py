"""Title normalization + fuzzy match."""
from streamload.catalog.match import (
    best_match,
    normalize_title,
    title_similarity,
)


def test_normalize_lowercases_and_strips():
    assert normalize_title("The Matrix") == "matrix"
    assert normalize_title("La Vita è Bella") == "vita e bella"


def test_normalize_drops_articles_in_languages():
    assert normalize_title("The Avengers") == "avengers"
    assert normalize_title("Le Pacte Des Loups") == "pacte des loups"
    assert normalize_title("Il Padrino") == "padrino"


def test_normalize_drops_year_in_parentheses():
    assert normalize_title("Dune (2021)") == "dune"


def test_similarity_identical_is_100():
    assert title_similarity("foo", "foo") == 100


def test_similarity_completely_different_is_low():
    assert title_similarity("Avengers", "Nightmare Before Christmas") < 50


def test_similarity_punctuation_insensitive():
    assert title_similarity("Spider-Man: No Way Home", "Spider Man No Way Home") >= 90


def test_best_match_picks_highest_score_above_threshold():
    candidates = [
        type("C", (), {"title": "The Matrix Reloaded", "year": 2003}),
        type("C", (), {"title": "The Matrix", "year": 1999}),
        type("C", (), {"title": "Matrix Revolution", "year": 2003}),
    ]
    pick = best_match(candidates, target_title="The Matrix", target_year=1999)
    assert pick is not None
    assert pick.year == 1999


def test_best_match_returns_none_when_below_threshold():
    candidates = [type("C", (), {"title": "Completely Different", "year": 2020})]
    pick = best_match(candidates, target_title="The Matrix", target_year=1999)
    assert pick is None


def test_best_match_year_proximity_breaks_ties():
    candidates = [
        type("C", (), {"title": "Star Wars", "year": 1977}),
        type("C", (), {"title": "Star Wars", "year": 2015}),
    ]
    pick = best_match(candidates, target_title="Star Wars", target_year=1977)
    assert pick.year == 1977
