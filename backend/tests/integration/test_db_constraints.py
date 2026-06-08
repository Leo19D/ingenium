"""Integration: DB-level CHECK constrainti odbijaju neispravne podatke
(obrana u dubinu uz app-level Pydantic validaciju)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.organization import Organization
from app.db.models.stock import StockItem, StockLocation

ORG = uuid.uuid4()


@pytest.mark.asyncio
async def test_negative_stock_rejected(db_session):
    org = Organization(id=ORG, name="X", slug="x", country_code="HR", base_currency="EUR")
    loc = StockLocation(id=uuid.uuid4(), org_id=ORG, name="L")
    db_session.add_all([org, loc])
    await db_session.flush()

    # quantity_on_hand >= 0 → negativna mora pasti na DB razini
    db_session.add(StockItem(
        id=uuid.uuid4(), org_id=ORG, location_id=loc.id, sku="NEG", name="Neg",
        unit="kom", quantity_on_hand=Decimal("-5"),
    ))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_valid_stock_ok(db_session):
    org = Organization(id=ORG, name="X", slug="x", country_code="HR", base_currency="EUR")
    loc = StockLocation(id=uuid.uuid4(), org_id=ORG, name="L")
    db_session.add_all([org, loc])
    await db_session.flush()
    db_session.add(StockItem(
        id=uuid.uuid4(), org_id=ORG, location_id=loc.id, sku="OK", name="Ok",
        unit="kom", quantity_on_hand=Decimal("10"),
    ))
    await db_session.flush()  # ne smije pasti
