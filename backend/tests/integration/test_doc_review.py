"""Integration: Document Review UI flow — kreiranje ponude iz UREĐENIH stavki.

Simulira ono što review tablica šalje: korisnik ispravi opis/količinu prije
generiranja ponude, frontend POSTa `selected_items` s `accepted_match`/`unit_price`.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_current_org_id, get_current_user
from app.db.models.document import Document, DocumentExtraction
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import get_db
from app.main import create_app

ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
DOC_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d1")


@pytest_asyncio.fixture
async def seeded(db_engine):
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        org = Organization(id=ORG_ID, name="Ingenium", slug="ingenium",
                            country_code="HR", base_currency="EUR")
        user = User(id=USER_ID, email="leo@ingeniumtrade.hr", full_name="Leo",
                    is_active=True, is_verified=True)
        doc = Document(id=DOC_ID, org_id=ORG_ID, storage_key="k", filename="rfq.xlsx",
                       status="parsed")
        ext = DocumentExtraction(
            document_id=DOC_ID,
            structured_data={"line_items": [
                # Originalna ekstrakcija — kriva količina, koju korisnik ispravlja
                {"position": 1, "description": "LED panel 60x60",
                 "quantity": 1, "unit": "pcs", "unit_price": 30.0,
                 "accepted_match": {"sku": "LED-6060", "name": "LED panel",
                                    "unit_cost": 20.0}},
            ]},
            extraction_method="xlsx", needs_review=True,
        )
        s.add_all([org, user, doc, ext])
        await s.commit()
    return factory


@pytest_asyncio.fixture
async def app_client(db_engine, seeded):
    app = create_app()
    factory = seeded

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
        yield ac


@pytest.mark.asyncio
async def test_create_quote_from_edited_items(app_client):
    """Korisnik ispravi qty 1→10 i opis; ponuda mora odražavati ispravke."""
    payload = {
        "project_name": "Hotel Adriatic",
        "currency": "EUR",
        "margin_pct": 0.20,
        "selected_items": [
            {"description": "LED panel 60x60 (ispravljen)", "quantity": 10,
             "unit": "pcs", "unit_price": 20.0,
             "accepted_match": {"sku": "LED-6060", "name": "LED panel",
                                "unit_cost": 20.0}},
        ],
    }
    r = await app_client.post(f"/api/v1/documents/{DOC_ID}/create-quote", json=payload)
    assert r.status_code == 201, r.text
    data = r.json()
    # unit_price = 20 / (1-0.20) = 25.00 ; total = 10 * 25 = 250.00
    assert data["total"] == pytest.approx(250.0), data


@pytest.mark.asyncio
async def test_empty_selected_items_falls_back_to_extraction(app_client):
    """Bez selected_items koristi originalnu ekstrakciju (qty=1)."""
    payload = {"project_name": "Fallback", "currency": "EUR", "margin_pct": 0.20}
    r = await app_client.post(f"/api/v1/documents/{DOC_ID}/create-quote", json=payload)
    assert r.status_code == 201, r.text
    # qty=1, unit_cost=20, price=25 → total=25
    assert r.json()["total"] == pytest.approx(25.0)
