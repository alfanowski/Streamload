from datetime import UTC, datetime, timedelta

from streamload.catalog.ranker import (
    DEFAULT_WEIGHTS,
    RankedSource,
    SourceMetrics,
    rank_sources,
)


def _ms(quality=720, latency=1000, success=10, fail=0, audio=("ita",), subs=("ita", "eng")):
    return SourceMetrics(
        service_short_name="x",
        service_url="https://x",
        service_media_id="1",
        quality_max_height=quality,
        latency_ttfb_ms=latency,
        success_count=success,
        failure_count=fail,
        audio_languages=list(audio),
        subtitle_languages=list(subs),
        last_verified_at=datetime.now(UTC),
    )


def test_higher_quality_wins_at_equal_other():
    sources = [
        _ms(quality=480), _ms(quality=720), _ms(quality=1080),
    ]
    ranked = rank_sources(sources)
    assert ranked[0].metrics.quality_max_height == 1080
    assert ranked[2].metrics.quality_max_height == 480


def test_labels_assigned_in_rank_order():
    sources = [_ms(quality=480), _ms(quality=1080)]
    ranked = rank_sources(sources)
    assert ranked[0].label == "Server 1"
    assert ranked[1].label == "Server 2"


def test_lower_latency_breaks_quality_tie():
    sources = [
        _ms(quality=720, latency=2000),
        _ms(quality=720, latency=400),
    ]
    ranked = rank_sources(sources)
    assert ranked[0].metrics.latency_ttfb_ms == 400


def test_unreliable_source_ranked_lower():
    a = _ms(quality=720, success=10, fail=0)
    b = _ms(quality=720, success=2, fail=8)
    ranked = rank_sources([b, a])
    assert ranked[0].metrics is a


def test_audio_match_boost_when_user_pref_present():
    # User wants 'ita' audio
    a = _ms(quality=720, audio=("eng",))
    b = _ms(quality=720, audio=("ita", "eng"))
    ranked = rank_sources([a, b], user_audio_pref="ita")
    assert ranked[0].metrics is b


def test_subs_match_boost_when_user_pref_present():
    a = _ms(quality=720, subs=("eng",))
    b = _ms(quality=720, subs=("ita", "eng"))
    ranked = rank_sources([a, b], user_subs_pref="ita")
    assert ranked[0].metrics is b


def test_score_is_normalized_0_to_100():
    sources = [_ms(quality=1080)]
    ranked = rank_sources(sources)
    assert 0 <= ranked[0].score <= 100


def test_empty_input_returns_empty_list():
    assert rank_sources([]) == []
