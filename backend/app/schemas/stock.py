"""Pydantic schemas za StockItem resource (skladište)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


class StockItemBase(BaseModel):
    sku: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)
    category: str | None = None
    unit: str = Field("pcs", max_length=16)
    quantity_on_hand: Decimal = Field(Decimal("0"), ge=0)
    quantity_reserved: Decimal = Field(Decimal("0"), ge=0)
    min_stock_level: Decimal = Field(Decimal("0"), ge=0)
    unit_cost: Decimal | None = Field(None, ge=0)
    currency: str = Field("EUR", min_length=3, max_length=3)
    notes: str | None = None


class StockItemCreate(StockItemBase):
    location_id: UUID | None = None
    product_id: UUID | None = None


class StockItemUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    unit: str | None = None
    quantity_on_hand: Decimal | None = None
    min_stock_level: Decimal | None = None
    unit_cost: Decimal | None = None
    currency: str | None = None
    notes: str | None = None


class StockItemResponse(StockItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    product_id: UUID | None
    location_id: UUID | None
    last_received_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> Literal["nema", "nisko", "na_stanju"]:
        """Status izvedeno iz količine i min razine."""
        if self.quantity_on_hand <= 0:
            return "nema"
        if self.quantity_on_hand < self.min_stock_level:
            return "nisko"
        return "na_stanju"


class StockBulkImportItem(BaseModel):
    sku: str = Field("")    # validira se u handleru
    naziv: str = Field("")  # validira se u handleru
    cat: str | None = None
    qty: str | None = None
    unit: str | None = None
    loc: str | None = None
    min: str | None = None
    price: str | None = None


class StockBulkImportRequest(BaseModel):
    items: list[StockBulkImportItem]
    location_name: str | None = None  # default lokacija ako nije po itemu


class StockLocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    country_code: str | None
