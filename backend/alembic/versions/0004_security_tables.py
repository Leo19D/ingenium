"""Perzistentne sigurnosne tablice — token blacklist + login rate limit.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-06

Dodaje:
- revoked_tokens: poništeni access tokeni (sha256 hash) do isteka — odjava
  sad preživi restart i dijeli se među workerima.
- login_attempts: pokušaji prijave po IP-u za sliding-window rate limit.

Vremena su epoch sekunde (Float) — portabilno SQLite/Postgres bez tz zavrzlama.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revoked_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("expires_epoch", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_revoked_tokens_expires_epoch", "revoked_tokens", ["expires_epoch"],
        if_not_exists=True,
    )

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("created_epoch", sa.Float(), nullable=False),
    )
    op.create_index("ix_login_attempts_ip", "login_attempts", ["ip"], if_not_exists=True)
    op.create_index(
        "ix_login_attempts_created_epoch", "login_attempts", ["created_epoch"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_login_attempts_created_epoch", "login_attempts", if_exists=True)
    op.drop_index("ix_login_attempts_ip", "login_attempts", if_exists=True)
    op.drop_table("login_attempts")
    op.drop_index("ix_revoked_tokens_expires_epoch", "revoked_tokens", if_exists=True)
    op.drop_table("revoked_tokens")
