"""Supplier model."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import CHAR, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedBase


class Supplier(TimestampedBase):
    __tablename__ = "suppliers"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    incoterms_default: Mapped[str | None] = mapped_column(String(8))  # EXW, FCA, DAP, DDP
    lead_time_days_avg: Mapped[int | None] = mapped_column()
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    on_time_rate: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    email: Mapped[str | None] = mapped_column(String(320))
    notes: Mapped[str | None] = mapped_column(Text)
