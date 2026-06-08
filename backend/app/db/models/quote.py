"""Quote, line items, and outcome tracking."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import TimestampedBase


class Quote(TimestampedBase):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_quotes_project_id_version"),
        CheckConstraint(
            "status IN ('draft','review','approved','sent','accepted','rejected','expired')",
            name="status",
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    fx_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    tax_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cost_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # our COGS
    margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    valid_until: Mapped[date | None] = mapped_column()
    payment_terms: Mapped[str | None] = mapped_column(Text)
    incoterms: Mapped[str | None] = mapped_column(String(16))
    delivery_terms: Mapped[str | None] = mapped_column(Text)
    notes_internal: Mapped[str | None] = mapped_column(Text)
    notes_external: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column()

    line_items = relationship(
        "QuoteLineItem", back_populates="quote", cascade="all, delete-orphan"
    )
    outcome = relationship("QuoteOutcome", back_populates="quote", uselist=False)


class QuoteLineItem(TimestampedBase):
    __tablename__ = "quote_line_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_quote_line_items_quantity_pos"),
        CheckConstraint("unit_price >= 0", name="ck_quote_line_items_price_nonneg"),
        CheckConstraint("discount_pct >= 0 AND discount_pct <= 1",
                        name="ck_quote_line_items_discount_range"),
    )

    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), index=True
    )
    supplier_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier_products.id"), index=True
    )
    # Veza na skladišnu stavku (iz catalog matchinga) — za pouzdano skidanje zalihe
    stock_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_items.id"), index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=0, nullable=False)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    notes: Mapped[str | None] = mapped_column(Text)

    quote = relationship("Quote", back_populates="line_items")


class QuoteOutcome(TimestampedBase):
    __tablename__ = "quote_outcomes"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('won','lost','withdrawn','expired','no_response')",
            name="outcome",
        ),
    )

    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(32))
    # price, delivery, quality, relationship, other
    competitor_name: Mapped[str | None] = mapped_column(Text)
    competitor_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    lessons: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )

    quote = relationship("Quote", back_populates="outcome")
