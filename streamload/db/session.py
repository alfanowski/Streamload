"""Async SQLAlchemy engine + session factory.

Module-level ``engine`` and ``async_session`` are populated by ``init()``
during FastAPI's lifespan. Tests construct their own engine via the
exported factory functions.
"""
from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async engine. ``url`` must use ``+asyncpg``."""
    return create_async_engine(
        url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to *engine*."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# Module-level globals filled by init().
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init(url: str) -> None:
    """Initialize module-level engine + session factory."""
    global _engine, _session_factory
    _engine = create_engine(url)
    _session_factory = create_session_factory(_engine)


async def shutdown() -> None:
    """Dispose the module-level engine."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a session per request."""
    if _session_factory is None:
        raise RuntimeError("DB session factory not initialized")
    async with _session_factory() as session:
        yield session
