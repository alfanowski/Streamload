from streamload.db.models import UserSettings, WatchHistory, SearchHistory, Event


def test_user_settings_pk():
    pk = {c.name for c in UserSettings.__table__.primary_key.columns}
    assert pk == {"user_id"}


def test_user_settings_columns():
    cols = {c.name for c in UserSettings.__table__.columns}
    assert cols >= {"user_id", "audio_pref_lang", "subs_pref_lang",
                    "quality_cap_height", "autoplay_next_episode", "skip_intro",
                    "theme", "locale", "updated_at"}


def test_watch_history_pk():
    pk = {c.name for c in WatchHistory.__table__.primary_key.columns}
    assert pk == {"user_id", "tmdb_id", "media_type", "season_number",
                  "episode_number", "completed_at"}


def test_search_history_pk():
    pk = {c.name for c in SearchHistory.__table__.primary_key.columns}
    assert pk == {"id"}


def test_search_history_has_query_hash_column():
    cols = {c.name for c in SearchHistory.__table__.columns}
    assert "query_hash" in cols
    assert "query_text" in cols


def test_event_pk():
    pk = {c.name for c in Event.__table__.primary_key.columns}
    assert pk == {"id"}


def test_event_payload_is_jsonb():
    from sqlalchemy.dialects.postgresql import JSONB
    payload_col = Event.__table__.c.payload
    assert isinstance(payload_col.type, JSONB)
