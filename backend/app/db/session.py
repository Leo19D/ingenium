"""
Async SQLAlchemy engine, session factory, FastAPI dependency.

Pool config se primjenjuje samo za "pravu" bazu (Postgres). SQLite koristi
StaticPool — bez pool config-a, da se može koristiti za testove.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

_engine_kwargs: dict = {"echo": settings.DB_ECHO, "pool_pre_ping": True}

if "sqlite" not in settings.DATABASE_URL:
    # Postgres / MySQL — koristi pool config
    _engine_kwargs.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
    )
else:
    # SQLite — bez pool overheada
    _engine_kwargs.pop("pool_pre_ping", None)

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional session."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
