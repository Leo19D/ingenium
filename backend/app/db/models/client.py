"""Client and Contact models."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import CHAR, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import TimestampedBase


class Client(TimestampedBase):
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("org_id", "tax_id", name="uq_clients_org_id_tax_id"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    legal_name: Mapped[str | None] = mapped_column(Text)
    tax_id: Mapped[str | None] = mapped_column(String(64))  # VAT number, EIN, etc.
    country_code: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(64))
    segment: Mapped[str | None] = mapped_column(String(32))  # hotel, retail, industrial...
    payment_terms_days: Mapped[int] = mapped_column(default=30, nullable=False)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))  # 0..1
    notes: Mapped[str | None] = mapped_column(Text)

    contacts = relationship("Contact", back_populates="client", cascade="all, delete-orphan")


class Contact(TimestampedBase):
    __tablename__ = "contacts"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(64))
    is_primary: Mapped[bool] = mapped_column(default=False, nullable=False)

    client = relationship("Client", back_populates="contacts")
