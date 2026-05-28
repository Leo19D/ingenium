"""Pydantic schemas for LLM I/O (extraction, matching, agent responses)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ExtractedLineItem(BaseModel):
    position: int | None = None
    description: str
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    currency: str | None = Field(None, description="ISO 4217 code")
    notes: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class ExtractedDocument(BaseModel):
    document_type: Literal["rfq", "quote", "price_list", "invoice", "other"]
    client_name: str | None = None
    client_tax_id: str | None = None
    project_name: str | None = None
    deadline: date | None = None
    currency: str | None = None
    language: str
    line_items: list[ExtractedLineItem] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class MatchProposal(BaseModel):
    product_sku: str
    product_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class LineItemAdvice(BaseModel):
    line_item_position: int
    matches: list[MatchProposal] = Field(default_factory=list)
    no_match: bool = False
    anomalies: list[str] = Field(default_factory=list)
    suggested_supplier_product_id: str | None = None
    supplier_reasoning: str | None = None


class AgentResponse(BaseModel):
    rfq_summary: list[str] = Field(default_factory=list, description="3-5 bullets for sales")
    line_items: list[LineItemAdvice] = Field(default_factory=list)
    overall_notes: str | None = None
