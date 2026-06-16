"""Nabava (procurement) — narudžbenice dobavljaču + kretanja zalihe.

Zatvara petlju: dobivena ponuda → narudžbenica (PO) dobavljaču → primka
(stock IN). Skidanje zalihe (stock OUT) događa se kad je ponuda dobivena.
Svako kretanje zalihe bilježi se u StockMovement (revizijski trag).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import TimestampedBase

# status: draft → sent → received | cancelled
PO_STATUSES = ("draft", "sent", "received", "cancelled")


class PurchaseOrder(TimestampedBase):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','sent','received','cancelled')",
            name="ck_purchase_orders_status",
        ),
        # Spriječi duplikate broja narudžbenice unutar organizacije (race/kolizija).
        UniqueConstraint("org_id", "po_number", name="uq_purchase_orders_org_number"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), index=True
    )
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quotes.id"), index=True
    )
    po_number: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), default="EUR", nullable=False)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    expected_date: Mapped[date | None] = mapped_column(Date)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    lines: Mapped[list[PurchaseOrderLine]] = relationship(
        back_populates="po", cascade="all, delete-orphan", lazy="selectin"
    )


class PurchaseOrderLine(TimestampedBase):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_purchase_order_lines_quantity_pos"),
        CheckConstraint("unit_cost >= 0", name="ck_purchase_order_lines_cost_nonneg"),
    )

    po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stock_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_items.id"), index=True
    )
    sku: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="pcs", nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    po: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class StockMovement(TimestampedBase):
    """Jedno kretanje zalihe (+ primka / − izdavanje / ± ručna korekcija)."""

    __tablename__ = "stock_movements"

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    stock_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stock_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delta: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)  # + ulaz / − izlaz
    reason: Mapped[str] = mapped_column(String(32), nullable=False)  # po_receipt|quote_won|manual
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)
