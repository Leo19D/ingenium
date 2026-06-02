"""Indexes for pagination + search performance.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-02

Dodaje:
- composite (org_id, created_at) za brzu paginaciju s ORDER BY created_at DESC
- pg_trgm GIN indekse na search kolone (samo PostgreSQL) za brz ILIKE

Napomena: pg_trgm dio se preskače na SQLite (dev) — ondje baza je mala
i nije potreban; u produkciji (Postgres) daje brzu pretragu.
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# (tablica, kolona za created_at composite)
_PAGINATED = ["clients", "suppliers", "stock_items", "products", "quotes", "projects"]

# (indeks_ime, tablica, kolona) za trigram pretragu — samo Postgres
_TRGM = [
    ("ix_trgm_clients_name", "clients", "name"),
    ("ix_trgm_suppliers_name", "suppliers", "name"),
    ("ix_trgm_stock_items_name", "stock_items", "name"),
    ("ix_trgm_stock_items_sku", "stock_items", "sku"),
    ("ix_trgm_products_name", "products", "name"),
    ("ix_trgm_products_sku", "products", "sku"),
]


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # Composite (org_id, created_at) — radi na svim bazama
    for table in _PAGINATED:
        op.create_index(
            f"ix_{table}_org_created",
            table,
            ["org_id", "created_at"],
            if_not_exists=True,
        )

    # pg_trgm GIN — samo Postgres
    if is_pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        for idx_name, table, col in _TRGM:
            op.execute(
                f"CREATE INDEX IF NOT EXISTS {idx_name} "
                f"ON {table} USING gin ({col} gin_trgm_ops)"
            )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        for idx_name, _table, _col in _TRGM:
            op.execute(f"DROP INDEX IF EXISTS {idx_name}")

    for table in _PAGINATED:
        op.drop_index(f"ix_{table}_org_created", table, if_exists=True)
