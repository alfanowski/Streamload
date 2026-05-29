from streamload.catalog.playability import heuristic_score
from streamload.catalog.tmdb import TmdbItem


def _item(**kw) -> TmdbItem:
    base = dict(
        tmdb_id=1, media_type="movie", title="X",
        original_language="en", origin_country=["US"],
        vote_count=500, popularity=50.0, year=2024,
    )
    base.update(kw)
    return TmdbItem(**base)


def test_western_movie_beats_eastern_movie():
    west = _item(origin_country=["US"], original_language="en")
    east = _item(origin_country=["KR"], original_language="ko")
    assert heuristic_score(west) > heuristic_score(east)


def test_italian_or_english_language_boosts():
    it = _item(original_language="it")
    de = _item(original_language="de")
    assert heuristic_score(it) > heuristic_score(de)


def test_popular_beats_obscure():
    popular = _item(vote_count=5000, popularity=200.0)
    obscure = _item(vote_count=2, popularity=0.3)
    assert heuristic_score(popular) > heuristic_score(obscure)


def test_anime_row_flips_origin_preference():
    jp = _item(media_type="tv", origin_country=["JP"], original_language="ja")
    us = _item(media_type="tv", origin_country=["US"], original_language="en")
    assert heuristic_score(jp, is_anime_row=True) > heuristic_score(us, is_anime_row=True)
    assert heuristic_score(us, is_anime_row=False) > heuristic_score(jp, is_anime_row=False)


def test_missing_fields_do_not_crash_and_score_low():
    bare = TmdbItem(tmdb_id=9, media_type="movie", title="Bare")
    s = heuristic_score(bare)
    assert 0.0 <= s <= 100.0


def test_score_is_bounded_0_100():
    maxed = _item(vote_count=100000, popularity=9999.0, original_language="it",
                  origin_country=["IT"], year=2025)
    s = heuristic_score(maxed)
    assert 0.0 <= s <= 100.0
