from streamload.catalog.collections import (
    COLLECTION_DEFS,
    CollectionDef,
    get_collection_def,
)


def test_all_definitions_have_unique_ids():
    ids = [d.id for d in COLLECTION_DEFS]
    assert len(ids) == len(set(ids))


def test_definitions_have_required_fields():
    for d in COLLECTION_DEFS:
        assert d.id
        assert d.title
        assert d.fetch
        assert d.refresh_ttl_hours > 0


def test_get_collection_def_lookup():
    d = get_collection_def("trending-day")
    assert d is not None
    assert d.id == "trending-day"


def test_get_collection_def_unknown_returns_none():
    assert get_collection_def("nonexistent") is None
