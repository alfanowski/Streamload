"""Orchestrator: TMDB items -> persist catalog state."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db.models import (
    CatalogItem,
    Collection,
    CollectionItem,
    TvEpisode,
)
from streamload.utils.logger import get_logger

from .tmdb import TmdbClient, TmdbItem

log = get_logger(__name__)


async def _upsert_catalog_item(db: AsyncSession, item: TmdbItem) -> None:
    stmt = insert(CatalogItem).values(
        tmdb_id=item.tmdb_id,
        media_type=item.media_type,
        title=item.title,
        original_title=item.original_title,
        year=item.year,
        poster_url=item.poster_url,
        backdrop_url=item.backdrop_url,
        overview=item.overview,
        rating=item.rating,
        runtime_minutes=item.runtime_minutes,
        seasons_count=item.seasons_count,
        genres=item.genres,
        metadata_fetched_at=datetime.now(UTC),
    ).on_conflict_do_update(
        index_elements=["tmdb_id", "media_type"],
        set_={
            "title": item.title,
            "original_title": item.original_title,
            "year": item.year,
            "poster_url": item.poster_url,
            "backdrop_url": item.backdrop_url,
            "overview": item.overview,
            "rating": item.rating,
            "runtime_minutes": item.runtime_minutes,
            "seasons_count": item.seasons_count,
            "genres": item.genres,
            "metadata_fetched_at": datetime.now(UTC),
        },
    )
    await db.execute(stmt)


async def ingest_collection(
    db: AsyncSession,
    *,
    collection_id: str,
    collection_title: str,
    media_type: Optional[str],
    sort_order: int,
    refresh_ttl_hours: int,
    items: list[TmdbItem],
) -> None:
    """Full ingest cycle for a collection (TMDB metadata only — v3 has no
    server-side scraping)."""
    log.info("Ingesting collection %s (%d items)", collection_id, len(items))

    coll_stmt = insert(Collection).values(
        id=collection_id, title=collection_title, media_type=media_type,
        sort_order=sort_order, refresh_ttl_hours=refresh_ttl_hours,
        last_refreshed_at=datetime.now(UTC),
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={
            "title": collection_title, "media_type": media_type,
            "sort_order": sort_order, "refresh_ttl_hours": refresh_ttl_hours,
            "last_refreshed_at": datetime.now(UTC),
        },
    )
    await db.execute(coll_stmt)

    for it in items:
        await _upsert_catalog_item(db, it)

    await db.execute(
        delete(CollectionItem).where(CollectionItem.collection_id == collection_id)
    )
    for pos, it in enumerate(items):
        db.add(CollectionItem(
            collection_id=collection_id, tmdb_id=it.tmdb_id,
            media_type=it.media_type, position=pos,
        ))

    await db.commit()
    log.info("Ingest complete for %s", collection_id)


async def _ingest_tv_episodes(
    db: AsyncSession,
    *,
    tmdb_id: int,
    seasons_count: int,
    tmdb: TmdbClient,
) -> int:
    """Pull every season's episode list from TMDB and upsert into tv_episodes."""
    from datetime import date as _date

    inserted = 0
    for season_number in range(1, (seasons_count or 0) + 1):
        try:
            data = await tmdb.get_tv_season(tmdb_id, season_number)
        except Exception:
            log.warning("TMDB season %s fetch failed for tmdb=%s", season_number, tmdb_id, exc_info=True)
            continue
        for ep in data.get("episodes", []):
            air = ep.get("air_date")
            air_d: _date | None = None
            if isinstance(air, str) and len(air) >= 10:
                try:
                    air_d = _date.fromisoformat(air[:10])
                except ValueError:
                    air_d = None
            still_url = None
            if ep.get("still_path"):
                still_url = f"https://image.tmdb.org/t/p/w300{ep['still_path']}"
            stmt = insert(TvEpisode).values(
                tmdb_id=tmdb_id,
                media_type="tv",
                season_number=season_number,
                episode_number=int(ep.get("episode_number", 0)),
                title=ep.get("name") or None,
                overview=ep.get("overview") or None,
                air_date=air_d,
                runtime_minutes=ep.get("runtime"),
                still_url=still_url,
            ).on_conflict_do_update(
                index_elements=["tmdb_id", "media_type", "season_number", "episode_number"],
                set_={
                    "title": ep.get("name") or None,
                    "overview": ep.get("overview") or None,
                    "air_date": air_d,
                    "runtime_minutes": ep.get("runtime"),
                    "still_url": still_url,
                },
            )
            await db.execute(stmt)
            inserted += 1
    return inserted


async def ingest_single_title(
    db: AsyncSession,
    *,
    item: TmdbItem,
    tmdb: "TmdbClient | None" = None,
) -> None:
    """Ingest one title on-demand: TMDB metadata + (for tv) per-season episodes.

    No reverse-lookup: source resolution lives in the v3 client.
    """
    log.info("Lazy-ingest tmdb_id=%s (%s)", item.tmdb_id, item.title)
    await _upsert_catalog_item(db, item)

    if item.media_type == "tv" and tmdb is not None and (item.seasons_count or 0) > 0:
        try:
            n = await _ingest_tv_episodes(
                db, tmdb_id=item.tmdb_id, seasons_count=item.seasons_count, tmdb=tmdb,
            )
            log.info("Ingested %d episodes for tmdb=%s", n, item.tmdb_id)
        except Exception:
            log.warning("Episode ingestion failed for tmdb=%s", item.tmdb_id, exc_info=True)

    await db.commit()
    log.info("Lazy-ingest done: tmdb_id=%s", item.tmdb_id)
