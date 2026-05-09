from streamload.db.models import (
    CatalogItem, Collection, CollectionItem, TvEpisode,
)


def test_catalog_item_columns():
    cols = {c.name for c in CatalogItem.__table__.columns}
    assert {"tmdb_id", "media_type", "title", "original_title", "year",
            "poster_url", "backdrop_url", "overview", "rating",
            "runtime_minutes", "seasons_count", "genres",
            "metadata_fetched_at"} <= cols


def test_catalog_item_pk():
    pk = {c.name for c in CatalogItem.__table__.primary_key.columns}
    assert pk == {"tmdb_id", "media_type"}


def test_collection_columns():
    cols = {c.name for c in Collection.__table__.columns}
    assert {"id", "title", "media_type", "sort_order",
            "refresh_ttl_hours", "last_refreshed_at"} <= cols


def test_collection_item_pk():
    pk = {c.name for c in CollectionItem.__table__.primary_key.columns}
    assert pk == {"collection_id", "tmdb_id", "media_type"}


def test_tv_episode_pk():
    pk = {c.name for c in TvEpisode.__table__.primary_key.columns}
    assert pk == {"tmdb_id", "media_type", "season_number", "episode_number"}
