"""Integration: semantičko catalog matchiranje — preraspored riječi, hrvatska
morfologija, sinonimi i mjerne jedinice (ono što stari leksički matcher promašuje).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.organization import Organization
from app.db.models.stock import StockItem, StockLocation
from app.services.matching.catalog_matcher import build_catalog_index, match_item

ORG = uuid.uuid4()

_CATALOG = [
    ("LED-6060-40", "LED panel ugradni 600x600 40W 4000K"),
    ("FLOOD-50", "LED reflektor 50W IP65 6500K"),
    ("CABLE-NYM-3", "Kabel NYM-J 3x1.5mm2"),
    ("BULB-E27-9", "LED zarulja E27 9W 2700K"),
    ("SW-1", "Prekidac jednopolni bijeli"),
]


@pytest_asyncio.fixture
async def index(db_engine):
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        db.add(Organization(id=ORG, name="X", slug="x", country_code="HR", base_currency="EUR"))
        loc = StockLocation(id=uuid.uuid4(), org_id=ORG, name="Glavno")
        db.add(loc)
        await db.flush()
        for sku, name in _CATALOG:
            db.add(StockItem(id=uuid.uuid4(), org_id=ORG, location_id=loc.id,
                             sku=sku, name=name, unit="kom"))
        await db.commit()
        yield await build_catalog_index(db, ORG), db


@pytest.mark.asyncio
@pytest.mark.parametrize("query,expected_sku", [
    ("Panel LED 60x60 40W 4000K nadgradni", "LED-6060-40"),  # preraspored + cm dimenzija
    ("reflektor 50w ip65", "FLOOD-50"),                       # mala slova, djelomično
    ("NYM-J kabel 3x1.5", "CABLE-NYM-3"),                     # preraspored riječi
    ("zarulje E27 9W", "BULB-E27-9"),                         # fleksija zarulja→zarulje
    ("sklopka jednopolna", "SW-1"),                           # sinonim sklopka→prekidac
])
async def test_semantic_top_match(index, query, expected_sku):
    idx, db = index
    res = await match_item(db=db, org_id=ORG, description=query, index=idx)
    assert res.candidates, f"nema kandidata za {query!r}"
    assert res.candidates[0].sku == expected_sku, \
        f"{query!r} → {res.candidates[0].sku} (očekivano {expected_sku})"


@pytest.mark.asyncio
async def test_exact_sku_wins(index):
    idx, db = index
    res = await match_item(db=db, org_id=ORG, description="nesto nepovezano",
                           sku_hint="CABLE-NYM-3", index=idx)
    assert res.accepted is not None
    assert res.accepted.sku == "CABLE-NYM-3"
    assert res.accepted.score == 1.0
