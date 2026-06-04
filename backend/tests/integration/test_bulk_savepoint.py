"""Integration: bulk import otpornost — duplikat usred batcha ne ruši prethodne.

Regresija za data-loss bug: `db.rollback()` po redu rušio je CIJELU sesiju,
brišući već flushane valjane redove i napuhujući `inserted`. Fix: savepoint
(`begin_nested`) po redu.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_current_org_id, get_current_user
from app.db.models.organization import Organization
from app.db.models.stock import StockItem
from app.db.models.user import User
from app.db.session import get_db
from app.main import create_app

ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


@pytest_asyncio.fixture
async def app_client(db_engine):
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add_all([
            Organization(id=ORG_ID, name="Ingenium", slug="ingenium",
                         country_code="HR", base_currency="EUR"),
            User(id=USER_ID, email="leo@ingeniumtrade.hr", full_name="Leo",
                 is_active=True, is_verified=True),
        ])
        await s.commit()

    app = create_app()

    async def override_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_org_id] = lambda: ORG_ID

    async def fake_user():
        async with factory() as s:
            return await s.get(User, USER_ID)

    app.dependency_overrides[get_current_user] = fake_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac._factory = factory  # type: ignore[attr-defined]
        yield ac


@pytest.mark.asyncio
async def test_duplicate_midbatch_preserves_valid_rows(app_client):
    # Pre-seed postojeći SKU
    await app_client.post("/api/v1/stock-items/bulk",
                          json={"items": [{"sku": "DUP", "naziv": "Existing"}]})
    # Batch: valjan, duplikat (IntegrityError), valjan
    r = await app_client.post("/api/v1/stock-items/bulk", json={"items": [
        {"sku": "GOOD1", "naziv": "Good One"},
        {"sku": "DUP", "naziv": "Collision"},
        {"sku": "GOOD2", "naziv": "Good Two"},
    ]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body == {"inserted": 2, "skipped": 1, "errors": []}, body

    # Stvarna perzistencija mora odgovarati prijavi
    async with app_client._factory() as s:  # type: ignore[attr-defined]
        skus = set((await s.execute(select(StockItem.sku))).scalars().all())
    assert {"DUP", "GOOD1", "GOOD2"} <= skus, skus
