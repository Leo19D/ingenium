"""Pydantic schemas za Client resource."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClientBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    legal_name: str | None = None
    tax_id: str | None = Field(None, max_length=64)
    country_code: str = Field("HR", min_length=2, max_length=2)
    industry: str | None = None
    segment: str | None = None
    payment_terms_days: int = Field(30, ge=0, le=365)
    credit_limit: Decimal | None = None
    risk_score: Decimal | None = Field(None, ge=0, le=1)
    notes: str | None = None


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    name: str | None = None
    legal_name: str | None = None
    tax_id: str | None = None
    country_code: str | None = None
    industry: str | None = None
    segment: str | None = None
    payment_terms_days: int | None = None
    credit_limit: Decimal | None = None
    risk_score: Decimal | None = None
    notes: str | None = None


class ClientResponse(ClientBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    created_at: datetime
    updated_at: datetime


class ClientBulkImportItem(BaseModel):
    """Jedan red iz Excel uvoza — manje strogo nego ClientCreate."""

    naziv: str = Field("")  # validira se u handleru (skip ako prazno)
    vat: str | None = None
    country: str | None = None
    segment: str | None = None
    payment: str | None = None  # može doći kao string iz Excela


class ClientBulkImportRequest(BaseModel):
    items: list[ClientBulkImportItem]


class BulkImportResult(BaseModel):
    inserted: int
    skipped: int
    errors: list[str] = Field(default_factory=list)
