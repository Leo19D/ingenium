"""Integration: izvještaji — agregacija ponuda/ishoda + Excel/PDF export."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_current_org_id
from app.db.models.organization import Organization
from app.db.models.project import Project
from app.db.models.quote import Quote, QuoteOutcome
from app.db.session import get_db
from app.main import create_app

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture
async def client(db_engine):
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        proj = Project(id=uuid.uuid4(), org_id=ORG, name="P", status="quoting")
        s.add_all([
            Organization(id=ORG, name="Ingenium", slug="ingenium",
                         country_code="HR", base_currency="EUR"),
            proj,
        ])
        # dobivena ponuda €1000 @ 25% marža, izgubljena €250 (razlog price)
        qw = Quote(id=uuid.uuid4(), org_id=ORG, project_id=proj.id, version=1,
                   status="accepted", currency="EUR", total=Decimal("1000"),
                   margin_pct=Decimal("0.25"))
        ql = Quote(id=uuid.uuid4(), org_id=ORG, project_id=proj.id, version=2,
                   status="rejected", currency="EUR", total=Decimal("250"))
        s.add_all([qw, ql])
        await s.flush()
        s.add_all([
            QuoteOutcome(id=uuid.uuid4(), quote_id=qw.id, outcome="won"),
            QuoteOutcome(id=uuid.uuid4(), quote_id=ql.id, outcome="lost", reason="price"),
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


def _period() -> str:
    today = date.today()
    return f"date_from={today.replace(day=1)}&date_to={today}"


@pytest.mark.asyncio
async def test_report_summary_aggregation(client):
    r = await client.get(f"/api/v1/reports/summary?{_period()}")
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["quotes"]["created"] == 2
    assert rep["outcomes"]["won"] == 1
    assert rep["outcomes"]["lost"] == 1
    assert rep["outcomes"]["won_value"] == 1000.0
    assert rep["outcomes"]["win_rate_pct"] == 50.0
    assert rep["outcomes"]["avg_margin_won_pct"] == 25.0
    assert rep["outcomes"]["top_lost_reasons"] == [["price", 1]]


@pytest.mark.asyncio
async def test_report_exports(client):
    rx = await client.get(f"/api/v1/reports/export/xlsx?{_period()}")
    assert rx.status_code == 200
    assert rx.content[:2] == b"PK"  # xlsx je zip
    assert len(rx.content) > 1000

    rp = await client.get(f"/api/v1/reports/export/pdf?{_period()}")
    assert rp.status_code == 200
    assert rp.content[:5] == b"%PDF-"


@pytest.mark.asyncio
async def test_report_empty_period(client):
    # razdoblje bez podataka → sve nule, bez pada
    r = await client.get("/api/v1/reports/summary?date_from=2020-01-01&date_to=2020-01-31")
    assert r.status_code == 200
    rep = r.json()
    assert rep["quotes"]["created"] == 0
    assert rep["outcomes"]["win_rate_pct"] == 0.0
    assert rep["outcomes"]["avg_margin_won_pct"] is None
