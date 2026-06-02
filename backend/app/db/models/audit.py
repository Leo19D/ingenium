"""Audit log — append-only, partitioned by month."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BIGINT, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# BIGINT autoincrement radi na Postgresu (BIGSERIAL); SQLite traži INTEGER PK.
_AUTO_PK = BIGINT().with_variant(Integer, "sqlite")


class AuditLog(Base):
    """Append-only audit trail. Partitioned by `at` in the real schema."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(_AUTO_PK, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 'quote.created','document.uploaded','price.changed', etc.
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    before_state: Mapped[dict | None] = mapped_column(JSONB)
    after_state: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False, index=True
    )
