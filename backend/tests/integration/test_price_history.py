"""Integration: memorija cijene po artiklu — /quotes/item-price-history."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_current_org_id
from app.db.models.organization import Organization
from app.db.models.project import Project
from app.db.models.quote import Quote, QuoteLineItem, QuoteOutcome
from app.db.session import get_db
from app.main import create_app

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
STOCK = uuid.UUID("00000000-0000-0000-0000-0000000000e1")


@pytest_asyncio.fixture
async def client(db_engine):
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        proj = Project(id=uuid.uuid4(), org_id=ORG, name="P", status="quoting")
        s.add_all([
            Organization(id=ORG, name="X", slug="x", country_code="HR", base_currency="EUR"),
            proj,
        ])
        await s.flush()
        # Dvije ponude s istim artiklom: €52 dobiveno, €48 izgubljeno
        for price, outcome, ver in [(52, "won", 1), (48, "lost", 2)]:
            q = Quote(id=uuid.uuid4(), org_id=ORG, project_id=proj.id, version=ver,
                      status="accepted", currency="EUR")
            s.add(q)
            await s.flush()
            s.add(QuoteLineItem(id=uuid.uuid4(), quote_id=q.id, position=1,
                                description="LED panel 60x60 40W", quantity=Decimal("10"),
                                unit="kom", unit_price=Decimal(price), unit_cost=Decimal("35"),
                                margin_pct=Decimal("0.30"), stock_item_id=STOCK))
            s.add(QuoteOutcome(id=uuid.uuid4(), quote_id=q.id, outcome=outcome))
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
async def test_history_by_description_similarity(client):
    # Reworded upit i dalje pogađa isti artikl (semantička sličnost)
    r = await client.get("/api/v1/quotes/item-price-history",
                         params={"description": "LED panel 60x60 40W nadgradni"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["matches"] == 2
    assert d["last_price"] == 52.0
    assert d["last_outcome"] == "won"
    assert d["won_count"] == 1
    assert d["avg_won_price"] == 52.0
    assert len(d["history"]) == 2


@pytest.mark.asyncio
async def test_history_by_stock_item_id(client):
    r = await client.get("/api/v1/quotes/item-price-history",
                         params={"stock_item_id": str(STOCK)})
    assert r.status_code == 200
    assert r.json()["matches"] == 2


@pytest.mark.asyncio
async def test_history_no_match(client):
    r = await client.get("/api/v1/quotes/item-price-history",
                         params={"description": "potpuno nepovezan artikl xyz"})
    assert r.status_code == 200
    assert r.json()["matches"] == 0


@pytest.mark.asyncio
async def test_history_empty_query(client):
    r = await client.get("/api/v1/quotes/item-price-history")
    assert r.status_code == 200
    assert r.json() == {"matches": 0, "history": []}
