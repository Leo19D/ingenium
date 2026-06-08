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


def _patch_metadata_for_sqlite() -> None:
    """Patch Postgres-only tipova za SQLite kompatibilnost.

    Radi se u dva koraka:
    1. Patch result_processor na UUID klasi (direktno, jer ORM mapper
       sprema referencu na tip pri prvom loadanu klase)
    2. Patch tipova u metadata tablicama (za DDL / create_all)
    """
    import uuid as _uuid_mod

    from sqlalchemy import JSON, String, Text, Uuid
    from sqlalchemy.dialects.postgresql import INET, JSONB, TSVECTOR
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    # 1. Monkey-patch UUID.result_processor da prihvati i int vrijednosti iz SQLite
    _orig_rp = PG_UUID.result_processor

    def _sqlite_result_processor(self, dialect, coltype):  # type: ignore[override]
        if dialect.name == "sqlite":
            def process(value):
                if value is None:
                    return None
                if isinstance(value, _uuid_mod.UUID):
                    return value
                if isinstance(value, int):
                    return _uuid_mod.UUID(int=value)
                return _uuid_mod.UUID(hex=str(value))
            return process
        return _orig_rp(self, dialect, coltype)

    PG_UUID.result_processor = _sqlite_result_processor  # type: ignore[method-assign]

    # 2. Patch tipova u metadata (za create_all DDL generiranje)
    import app.db.models  # noqa: F401
    from app.db.base import Base

    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
            elif isinstance(col.type, INET):
                col.type = String(45)
            elif isinstance(col.type, TSVECTOR):
                col.type = Text()
            elif isinstance(col.type, PG_UUID):
                col.type = Uuid(as_uuid=True, native_uuid=False)


_engine_kwargs: dict = {"echo": settings.DB_ECHO, "pool_pre_ping": True}

if "sqlite" not in settings.DATABASE_URL:
    # Postgres / MySQL — koristi pool config
    _engine_kwargs.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
    )
    # Supabase/managed Postgres traži SSL (asyncpg)
    if settings.DB_SSL or "supabase." in settings.DATABASE_URL:
        _connect: dict = {"ssl": "require"}
        # pgbouncer (Supabase pooler) ne podnosi prepared statement cache
        if "pooler.supabase" in settings.DATABASE_URL:
            _connect["statement_cache_size"] = 0
        _engine_kwargs["connect_args"] = _connect
else:
    # SQLite — bez pool overheada (patch se zove iz main.lifespan)
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
