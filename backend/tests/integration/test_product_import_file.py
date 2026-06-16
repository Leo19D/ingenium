"""Integration: uvoz kataloga / cjenika dobavljača — /products/import-file."""

from __future__ import annotations

import io
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_current_org_id
from app.db.models.organization import Organization
from app.db.models.supplier import Supplier
from app.db.session import get_db
from app.main import create_app

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
SUPPLIER = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


@pytest_asyncio.fixture
async def client(db_engine):
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add(Organization(id=ORG, name="X", slug="x", country_code="HR", base_currency="EUR"))
        s.add(
            Supplier(id=SUPPLIER, org_id=ORG, name="Trilux GmbH", country_code="DE", currency="EUR")
        )
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


def _xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Šifra", "Naziv artikla", "Kategorija", "JM", "Nabavna cijena"])
    ws.append(["LED-6060", "LED panel 60x60 40W", "rasvjeta", "kom", "28,50"])
    ws.append(["KBL-15", "Kabel NYM 3x1.5", "kabel", "m", "1,15"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.asyncio
async def test_catalog_import_saves_category_and_unit(client):
    """Uvoz bez dobavljača: kategorija + JM se spremaju, cijene se NE vežu."""
    r = await client.post(
        "/api/v1/products/import-file",
        files={"file": ("katalog.xlsx", _xlsx(), _XLSX_MIME)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted"] == 2
    assert body["prices_linked"] == 0

    items = (await client.get("/api/v1/products/?search=LED panel")).json()["items"]
    led = next(i for i in items if i["sku"] == "LED-6060")
    assert led["category"] == "rasvjeta"
    assert led["unit"] == "kom"


@pytest.mark.asyncio
async def test_supplier_price_list_links_prices(client):
    """Uvoz s supplier_id: kreira Proizvod↔Dobavljač vezu + cijenu u history."""
    r = await client.post(
        "/api/v1/products/import-file",
        data={"supplier_id": str(SUPPLIER), "currency": "EUR"},
        files={"file": ("cjenik.xlsx", _xlsx(), _XLSX_MIME)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted"] == 2
    assert body["prices_linked"] == 2

    items = (await client.get("/api/v1/products/?search=LED panel")).json()["items"]
    led = next(i for i in items if i["sku"] == "LED-6060")
    links = (await client.get(f"/api/v1/products/{led['id']}/suppliers")).json()
    assert len(links) == 1
    assert links[0]["supplier_name"] == "Trilux GmbH"
    assert float(links[0]["unit_price"]) == 28.5
    assert links[0]["currency"] == "EUR"


@pytest.mark.asyncio
async def test_import_unknown_supplier_404(client):
    r = await client.post(
        "/api/v1/products/import-file",
        data={"supplier_id": str(uuid.uuid4())},
        files={"file": ("cjenik.xlsx", _xlsx(), _XLSX_MIME)},
    )
    assert r.status_code == 404


def test_parse_price_eu_formats():
    """_parse_price: EU formati uklj. tisuće bez decimala ('1.234' = 1234)."""
    from decimal import Decimal

    from app.api.v1.products import _parse_price

    assert _parse_price("28,50") == Decimal("28.50")
    assert _parse_price("1.234,56") == Decimal("1234.56")
    assert _parse_price("1.234") == Decimal("1234")   # tisuće, NE 1.234
    assert _parse_price("12.500") == Decimal("12500")
    assert _parse_price("1.50") == Decimal("1.50")    # decimala, NE tisuće
    assert _parse_price("1234.56") == Decimal("1234.56")
    assert _parse_price("") is None
    assert _parse_price("0") is None
