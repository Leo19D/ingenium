"""Tax rules per jurisdiction + transaction type."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedBase


class TaxRule(TimestampedBase):
    __tablename__ = "tax_rules"

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )
    country_code: Mapped[str] = mapped_column(CHAR(2), nullable=False, index=True)
    region: Mapped[str | None] = mapped_column(String(64))  # US state, etc.
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 'vat','sales_tax','gst','reverse_charge','zero_rated','export_exempt'
    rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    applies_when: Mapped[dict | None] = mapped_column(JSONB)  # conditions
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
