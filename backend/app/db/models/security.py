"""Sigurnosne tablice — perzistentni token blacklist i rate-limit tragovi.

Prije: in-memory dict u procesu → gubio se na restart i nije dijeljen među
workerima (odjavljeni token opet valjan nakon restarta). Sad: DB izvor istine.

Vremena su epoch sekunde (float) — portabilno između SQLite i Postgresa bez
timezone serijalizacijskih zavrzlama.
"""

from __future__ import annotations

from sqlalchemy import BIGINT, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# BIGINT autoincrement na Postgresu (BIGSERIAL); SQLite traži INTEGER PK.
_AUTO_PK = BIGINT().with_variant(Integer, "sqlite")


class RevokedToken(Base):
    """Poništen (odjavljen) access token — pamti se do isteka tokena."""

    __tablename__ = "revoked_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 hex
    expires_epoch: Mapped[float] = mapped_column(Float, nullable=False, index=True)


class LoginAttempt(Base):
    """Jedan pokušaj prijave po IP-u — za sliding-window rate limit."""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(_AUTO_PK, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_epoch: Mapped[float] = mapped_column(Float, nullable=False, index=True)
