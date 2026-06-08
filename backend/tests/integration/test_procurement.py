"""Integration: nabavni ciklus — dobivena ponuda skida zalihu, narudžbenica
iz ponude, primka vraća zalihu u skladište. + revizijski trag kretanja."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import (
    get_current_org_id,
    get_current_role,
    get_current_user,
)
from app.db.models.organization import Organization
from app.db.models.procurement import StockMovement
from app.db.models.project import Project
from app.db.models.quote import Quote, QuoteLineItem
from app.db.models.stock import StockItem, StockLocation
from app.db.models.user import User
from app.db.session import get_db
from app.main import create_app

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
PROJ = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
QUOTE = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
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
            StockItem(id=STOCK, org_id=ORG, location_id=loc.id, sku="PANEL",
                      name="LED panel", unit="kom", quantity_on_hand=Decimal("100"),
                      unit_cost=Decimal("20")),
            Project(id=PROJ, org_id=ORG, name="Hotel", status="quoting"),
            Quote(id=QUOTE, org_id=ORG, project_id=PROJ, version=1,
                  status="sent", currency="EUR"),
            QuoteLineItem(id=uuid.uuid4(), quote_id=QUOTE, position=1,
                          description="LED panel", quantity=Decimal("30"), unit="kom",
                          unit_price=Decimal("30"), unit_cost=Decimal("20"),
                          stock_item_id=STOCK),
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
    app.dependency_overrides[get_current_role] = lambda: "owner"

    async def fake_user():
        async with factory() as s:
            return await s.get(User, USER)

    app.dependency_overrides[get_current_user] = fake_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac._factory = factory  # type: ignore[attr-defined]
        yield ac


async def _qty(ac) -> Decimal:
    async with ac._factory() as s:  # type: ignore[attr-defined]
        return (await s.get(StockItem, STOCK)).quantity_on_hand


@pytest.mark.asyncio
async def test_full_procurement_loop(app_client):
    assert await _qty(app_client) == Decimal("100")

    # Ponuda dobivena → skini 30
    r = await app_client.post(f"/api/v1/quotes/{QUOTE}/outcome", json={"outcome": "won"})
    assert r.status_code == 201, r.text
    assert r.json()["stock_deducted_lines"] == 1
    assert await _qty(app_client) == Decimal("70")

    # Narudžbenica iz ponude
    r = await app_client.post(f"/api/v1/purchase-orders/from-quote/{QUOTE}")
    assert r.status_code == 201, r.text
    po = r.json()
    assert po["status"] == "draft"
    assert po["total"] == "600.00"  # 30 * 20
    poid = po["id"]

    # Primka → vrati 30 u skladište
    r = await app_client.post(f"/api/v1/purchase-orders/{poid}/receive")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received"
    assert await _qty(app_client) == Decimal("100")

    # Ponovna primka → 409
    assert (await app_client.post(f"/api/v1/purchase-orders/{poid}/receive")).status_code == 409

    # Revizijski trag: 1 izlaz (quote_won) + 1 ulaz (po_receipt)
    async with app_client._factory() as s:  # type: ignore[attr-defined]
        moves = (await s.execute(select(StockMovement).where(StockMovement.stock_item_id == STOCK))).scalars().all()
    reasons = sorted(m.reason for m in moves)
    assert reasons == ["po_receipt", "quote_won"], reasons


@pytest.mark.asyncio
async def test_role_gate_blocks_viewer(app_client):
    """Viewer ne smije kreirati narudžbenicu."""
    app_client._transport.app.dependency_overrides[get_current_role] = lambda: "viewer"  # type: ignore[attr-defined]
    r = await app_client.post("/api/v1/purchase-orders/", json={
        "lines": [{"description": "X", "quantity": 1, "unit_cost": 5}],
    })
    assert r.status_code == 403, r.text
