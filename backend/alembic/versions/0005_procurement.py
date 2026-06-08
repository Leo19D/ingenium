"""Nabava — purchase_orders, purchase_order_lines, stock_movements +
quote_line_items.stock_item_id.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", UUID(as_uuid=True), sa.ForeignKey("suppliers.id"), nullable=True),
        sa.Column("quote_id", UUID(as_uuid=True), sa.ForeignKey("quotes.id"), nullable=True),
        sa.Column("po_number", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("currency", sa.CHAR(3), nullable=False, server_default="EUR"),
        sa.Column("subtotal", sa.Numeric(14, 2)),
        sa.Column("total", sa.Numeric(14, 2)),
        sa.Column("notes", sa.Text()),
        sa.Column("expected_date", sa.Date()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_purchase_orders_org_id", "purchase_orders", ["org_id"], if_not_exists=True)

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("po_id", UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stock_item_id", UUID(as_uuid=True), sa.ForeignKey("stock_items.id"), nullable=True),
        sa.Column("sku", sa.String(128)),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False, server_default="pcs"),
        sa.Column("unit_cost", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(14, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_purchase_order_lines_po_id", "purchase_order_lines", ["po_id"], if_not_exists=True)

    op.create_table(
        "stock_movements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("stock_item_id", UUID(as_uuid=True), sa.ForeignKey("stock_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delta", sa.Numeric(14, 4), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("ref_type", sa.String(32)),
        sa.Column("ref_id", UUID(as_uuid=True)),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_stock_movements_org_id", "stock_movements", ["org_id"], if_not_exists=True)
    op.create_index("ix_stock_movements_stock_item_id", "stock_movements", ["stock_item_id"], if_not_exists=True)

    op.add_column(
        "quote_line_items",
        sa.Column("stock_item_id", UUID(as_uuid=True), sa.ForeignKey("stock_items.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("quote_line_items", "stock_item_id")
    op.drop_table("stock_movements")
    op.drop_table("purchase_order_lines")
    op.drop_table("purchase_orders")
