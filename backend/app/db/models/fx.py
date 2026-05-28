"""FX rate snapshots — append-only."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, Numeric, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (
        PrimaryKeyConstraint("base_ccy", "quote_ccy", "as_of"),
    )

    base_ccy: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    quote_ccy: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # ecb, oxr, manual
    as_of: Mapped[datetime] = mapped_column(nullable=False)
