"""Add OTP fields to users table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("otp_hash", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("otp_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("otp_attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "otp_attempts")
    op.drop_column("users", "otp_expires_at")
    op.drop_column("users", "otp_hash")
