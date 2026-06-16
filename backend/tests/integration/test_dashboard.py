"""Integration: konsolidirani dashboard — /analytics/dashboard."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_current_org_id
from app.db.models.client import Client
from app.db.models.organization import Organization
from app.db.models.procurement import PurchaseOrder
from app.db.models.project import Project
from app.db.models.quote import Quote, QuoteLineItem, QuoteOutcome
from app.db.models.stock import StockItem
from app.db.session import get_db
from app.main import create_app

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
CLIENT = uuid.UUID("00000000-0000-0000-0000-0000000000c5")
PROJ = uuid.UUID("00000000-0000-0000-0000-0000000000b5")
QUOTE = uuid.UUID("00000000-0000-0000-0000-0000000000a5")


@pytest_asyncio.fixture
async def client(db_engine):
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add_all([
            Organization(id=ORG, name="X", slug="x", country_code="HR", base_currency="EUR"),
            Client(id=CLIENT, org_id=ORG, name="Hotel Adriatic", country_code="HR"),
            Project(id=PROJ, org_id=ORG, name="Rasvjeta", client_id=CLIENT, status="quoting"),
            Quote(id=QUOTE, org_id=ORG, project_id=PROJ, version=1, status="sent",
                  currency="EUR", total=Decimal("5000"), margin_pct=Decimal("0.30")),
            QuoteOutcome(id=uuid.uuid4(), quote_id=QUOTE, outcome="won"),
            QuoteLineItem(id=uuid.uuid4(), quote_id=QUOTE, position=1, description="LED panel 60x60",
                          quantity=Decimal("100"), unit="kom", unit_price=Decimal("30"),
                          line_total=Decimal("3000")),
            StockItem(id=uuid.uuid4(), org_id=ORG, sku="P1", name="Panel", unit="kom",
                      quantity_on_hand=Decimal("50"), min_stock_level=Decimal("10"),
                      unit_cost=Decimal("20")),
            PurchaseOrder(id=uuid.uuid4(), org_id=ORG, po_number="PO-1", status="draft",
                          currency="EUR", total=Decimal("800")),
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
@pytest.mark.parametrize("period", ["month", "quarter", "year"])
async def test_dashboard_returns_all_sections(client, period):
    r = await client.get(f"/api/v1/analytics/dashboard?period={period}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["period"] == period

    k = d["kpis"]
    assert k["won_value"] == 5000.0          # jedna dobivena ponuda
    assert k["win_rate"] == 100.0
    assert k["avg_margin"] == 30.0

    # top klijent = Hotel Adriatic s dobivenom vrijednošću
    assert any(c["name"] == "Hotel Adriatic" and c["won_value"] == 5000.0 for c in d["top_clients"])
    # top artikl = LED panel
    assert any("LED panel" in p["description"] for p in d["top_products"])
    # nabava: 1 otvorena narudžbenica + vrijednost zaliha
    assert d["procurement"]["open_po_count"] == 1
    assert d["procurement"]["stock_value"] == 1000.0   # 50 * 20


@pytest.mark.asyncio
async def test_dashboard_invalid_period_defaults_to_month(client):
    r = await client.get("/api/v1/analytics/dashboard?period=nonsense")
    assert r.status_code == 200
    assert r.json()["period"] == "month"
