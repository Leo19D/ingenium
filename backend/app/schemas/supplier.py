"""Pydantic schemas za Supplier resource."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SupplierBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    country_code: str = Field("HR", min_length=2, max_length=2)
    currency: str = Field("EUR", min_length=3, max_length=3)
    incoterms_default: str | None = Field(None, max_length=8)
    lead_time_days_avg: int | None = Field(None, ge=0)
    rating: Decimal | None = Field(None, ge=0, le=5)
    on_time_rate: Decimal | None = Field(None, ge=0, le=1)
    quality_score: Decimal | None = Field(None, ge=0, le=1)
    email: str | None = None
    notes: str | None = None


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: str | None = None
    country_code: str | None = None
    currency: str | None = None
    incoterms_default: str | None = None
    lead_time_days_avg: int | None = None
    rating: Decimal | None = None
    on_time_rate: Decimal | None = None
    quality_score: Decimal | None = None
    email: str | None = None
    notes: str | None = None


class SupplierResponse(SupplierBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    created_at: datetime
    updated_at: datetime


class SupplierBulkImportItem(BaseModel):
    naziv: str = Field("")  # validira se u handleru
    country: str | None = None
    currency: str | None = None
    incoterms: str | None = None
    lead: str | None = None


class SupplierBulkImportRequest(BaseModel):
    items: list[SupplierBulkImportItem]
