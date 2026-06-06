"""Shared pytest fixtures — SQLite in-memory baza za brze testove."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_db
from app.main import create_app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


def _patch_pg_types(metadata) -> None:
    """Zamijeni Postgres-specific tipove s SQLite-compatible alternativama."""
    from sqlalchemy import String, Text, Uuid
    from sqlalchemy.dialects.postgresql import INET, JSONB, TSVECTOR
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID
    for table in metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
            elif isinstance(col.type, INET):
                col.type = String(45)
            elif isinstance(col.type, TSVECTOR):
                col.type = Text()
            elif isinstance(col.type, PG_UUID):
                col.type = Uuid(as_uuid=True, native_uuid=False)


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    _patch_pg_types(Base.metadata)
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(db_engine):
    app = create_app()

    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
