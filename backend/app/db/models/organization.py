"""Organization (multi-tenant root)."""

from __future__ import annotations

from sqlalchemy import CHAR, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import TimestampedBase


class Organization(TimestampedBase):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    country_code: Mapped[str] = mapped_column(CHAR(2), nullable=False)  # ISO 3166-1
    base_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)  # ISO 4217
    locale: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships (back_populates avoided for brevity — add when needed)
    memberships = relationship("Membership", back_populates="organization", cascade="all, delete-orphan")
