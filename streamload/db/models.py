"""SQLAlchemy ORM models.

Mirrors the schema in `docs/superpowers/specs/2026-05-08-streamload-v2-design.md` §5.1.
Migrations are managed by Alembic; these models are the source of truth.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    email_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(
        Text, nullable=False, default="user", server_default="user",
    )
    locale: Mapped[str] = mapped_column(
        Text, nullable=False, default="it-IT", server_default="it-IT",
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    disabled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )
    email_tokens: Mapped[list["EmailToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )
    webauthn_credentials: Mapped[list["WebauthnCredential"]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
    )


class Session(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="sessions")


class EmailToken(Base):
    __tablename__ = "email_tokens"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    consumed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    user: Mapped[User] = relationship(back_populates="email_tokens")

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('verify_email', 'reset_password')",
            name="ck_email_tokens_purpose",
        ),
    )


class WebauthnCredential(Base):
    __tablename__ = "webauthn_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    credential_id: Mapped[bytes] = mapped_column(
        LargeBinary, unique=True, nullable=False,
    )
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    transports: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}",
    )
    nickname: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    user: Mapped[User] = relationship(back_populates="webauthn_credentials")


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    original_title: Mapped[Optional[str]] = mapped_column(Text)
    year: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    poster_url: Mapped[Optional[str]] = mapped_column(Text)
    backdrop_url: Mapped[Optional[str]] = mapped_column(Text)
    overview: Mapped[Optional[str]] = mapped_column(Text)
    rating: Mapped[Optional[float]] = mapped_column(Numeric(3, 1))
    runtime_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    seasons_count: Mapped[Optional[int]] = mapped_column(Integer)
    genres: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default="{}")
    metadata_fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    sources: Mapped[list["CatalogSource"]] = relationship(
        back_populates="item", cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("media_type IN ('movie', 'tv')", name="ck_catalog_items_media_type"),
    )


class CatalogSource(Base):
    __tablename__ = "catalog_sources"

    tmdb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("catalog_items.tmdb_id", ondelete="CASCADE"), primary_key=True,
    )
    service_short_name: Mapped[str] = mapped_column(Text, primary_key=True, index=True)
    service_url: Mapped[str] = mapped_column(Text, nullable=False)
    service_media_id: Mapped[str] = mapped_column(Text, nullable=False)
    quality_max_height: Mapped[Optional[int]] = mapped_column(Integer)
    languages_audio: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default="{}")
    languages_subs: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default="{}")
    last_verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    item: Mapped[CatalogItem] = relationship(back_populates="sources")


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[Optional[str]] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    refresh_ttl_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24, server_default="24")
    last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["CollectionItem"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan",
    )


class CollectionItem(Base):
    __tablename__ = "collection_items"

    collection_id: Mapped[str] = mapped_column(
        Text, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True,
    )
    tmdb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("catalog_items.tmdb_id", ondelete="CASCADE"), primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    collection: Mapped[Collection] = relationship(back_populates="items")


class TvEpisode(Base):
    __tablename__ = "tv_episodes"

    tmdb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("catalog_items.tmdb_id", ondelete="CASCADE"), primary_key=True,
    )
    season_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(Text)
    overview: Mapped[Optional[str]] = mapped_column(Text)
    air_date: Mapped[Optional[Date]] = mapped_column(Date)
    runtime_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    still_url: Mapped[Optional[str]] = mapped_column(Text)


class WatchProgress(Base):
    __tablename__ = "watch_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    tmdb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("catalog_items.tmdb_id", ondelete="CASCADE"), primary_key=True,
    )
    season_number: Mapped[int] = mapped_column(Integer, primary_key=True, default=0, server_default="0")
    episode_number: Mapped[int] = mapped_column(Integer, primary_key=True, default=0, server_default="0")
    position_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    last_source: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class Favorite(Base):
    __tablename__ = "favorites"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    tmdb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("catalog_items.tmdb_id", ondelete="CASCADE"), primary_key=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class Watchlist(Base):
    __tablename__ = "watchlist"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    tmdb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("catalog_items.tmdb_id", ondelete="CASCADE"), primary_key=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class IntroMarker(Base):
    __tablename__ = "intro_markers"

    tmdb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("catalog_items.tmdb_id", ondelete="CASCADE"), primary_key=True,
    )
    season_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    intro_start_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    intro_end_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    outro_start_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    detected_by: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))

    __table_args__ = (
        CheckConstraint(
            "detected_by IN ('fingerprint', 'manual')",
            name="ck_intro_markers_detected_by",
        ),
    )
