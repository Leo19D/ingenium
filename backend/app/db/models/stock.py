"""Stock location and stock item models (skladište)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedBase


class StockLocation(TimestampedBase):
    __tablename__ = "stock_locations"

    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(CHAR(2))


class StockItem(TimestampedBase):
    __tablename__ = "stock_items"
    __table_args__ = (
        UniqueConstraint("org_id", "sku", "location_id"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        index=True,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("stock_locations.id"),
    )
    sku: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(16), default="pcs", nullable=False)
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    quantity_reserved: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    min_stock_level: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    currency: Mapped[str] = mapped_column(CHAR(3), default="EUR", nullable=False)
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
