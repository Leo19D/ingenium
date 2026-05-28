"""Project (umbrella for one RFQ / deal)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedBase


class Project(TimestampedBase):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','quoting','submitted','won','lost','withdrawn','on_hold')",
            name="status",
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    project_type: Mapped[str | None] = mapped_column(String(32))
    # hotel, office, residential, industrial, public_lighting, retail, ...
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    estimated_value_ccy: Mapped[str | None] = mapped_column(CHAR(3))
    deadline_at: Mapped[datetime | None] = mapped_column()
    site_country: Mapped[str | None] = mapped_column(CHAR(2))
    site_region: Mapped[str | None] = mapped_column(String(64))
    urgency: Mapped[str | None] = mapped_column(String(16))  # normal, urgent, critical
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
