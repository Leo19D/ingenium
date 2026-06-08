"""Integration: skladišne operacije — ručna korekcija (+/−), povijest kretanja,
low-stock status i role gate."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_current_org_id, get_current_role, get_current_user
from app.db.models.organization import Organization
from app.db.models.stock import StockItem, StockLocation
from app.db.models.user import User
from app.db.session import get_db
from app.main import create_app

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
STOCK = uuid.UUID("00000000-0000-0000-0000-0000000000e1")


@pytest_asyncio.fixture
async def app_client(db_engine):
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        loc = StockLocation(id=uuid.uuid4(), org_id=ORG, name="Glavno")
        s.add_all([
            Organization(id=ORG, name="Ingenium", slug="ingenium",
                         country_code="HR", base_currency="EUR"),
            User(id=USER, email="leo@ingeniumtrade.hr", full_name="Leo",
                 is_active=True, is_verified=True),
            loc,
            StockItem(id=STOCK, org_id=ORG, location_id=loc.id, sku="A1",
                      name="Artikl", unit="kom", quantity_on_hand=Decimal("5"),
                      min_stock_level=Decimal("10"), unit_cost=Decimal("3")),
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
    app.dependency_overrides[get_current_org_id] = lambda: ORG
    app.dependency_overrides[get_current_role] = lambda: "procurement"

    async def fake_user():
        async with factory() as s:
            return await s.get(User, USER)

    app.dependency_overrides[get_current_user] = fake_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, app


@pytest.mark.asyncio
async def test_adjust_and_movements_and_status(app_client):
    ac, _ = app_client
    # Početni status: 5 < min 10 → nisko
    r = await ac.get(f"/api/v1/stock-items/{STOCK}")
    assert r.json()["status"] == "nisko"

    # Ulaz +20 → 25, status na_stanju
    r = await ac.post(f"/api/v1/stock-items/{STOCK}/adjust", json={"delta": 20, "note": "Inventura"})
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["quantity_on_hand"]) == Decimal("25")
    assert r.json()["status"] == "na_stanju"

    # Izlaz −30 → clamp na 0, status nema
    r = await ac.post(f"/api/v1/stock-items/{STOCK}/adjust", json={"delta": -30})
    assert Decimal(r.json()["quantity_on_hand"]) == Decimal("0")
    assert r.json()["status"] == "nema"

    # delta 0 → 422
    assert (await ac.post(f"/api/v1/stock-items/{STOCK}/adjust", json={"delta": 0})).status_code == 422

    # Povijest: 2 kretanja (oba ručna). Redoslijed unutar iste sekunde je
    # nedefiniran na SQLite-u (sek. rezolucija) — provjeravamo skup, ne poredak.
    r = await ac.get(f"/api/v1/stock-items/{STOCK}/movements")
    moves = r.json()
    assert len(moves) == 2
    assert {Decimal(m["delta"]) for m in moves} == {Decimal("20"), Decimal("-30")}
    assert all(m["reason"] == "manual" for m in moves)


@pytest.mark.asyncio
async def test_adjust_role_gate(app_client):
    ac, app = app_client
    app.dependency_overrides[get_current_role] = lambda: "viewer"
    r = await ac.post(f"/api/v1/stock-items/{STOCK}/adjust", json={"delta": 1})
    assert r.status_code == 403
