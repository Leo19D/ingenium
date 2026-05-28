"""Product, SupplierProduct, and price history models.

Product = canonical item in our catalog.
SupplierProduct = mapping of our product to one supplier's offering.
SupplierPriceHistory = append-only price changes per supplier_product.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BIGINT,
    CHAR,
    Boolean,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.db.base import Base, TimestampedBase, UUIDPrimaryKey


class Product(TimestampedBase):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("org_id", "sku", name="uq_products_org_id_sku"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    brand: Mapped[str | None] = mapped_column(String(128))
    specs: Mapped[dict | None] = mapped_column(JSONB)
    unit: Mapped[str] = mapped_column(String(16), default="pcs", nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.EMBEDDING_DIM))
    search_text: Mapped[str | None] = mapped_column(TSVECTOR)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    supplier_products = relationship(
        "SupplierProduct", back_populates="product", cascade="all, delete-orphan"
    )


class SupplierProduct(TimestampedBase):
    __tablename__ = "supplier_products"
    __table_args__ = (
        UniqueConstraint("product_id", "supplier_id"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_sku: Mapped[str | None] = mapped_column(String(128))
    supplier_name: Mapped[str | None] = mapped_column(Text)  # how supplier calls it
    moq: Mapped[int] = mapped_column(default=1, nullable=False)
    pack_size: Mapped[int] = mapped_column(default=1, nullable=False)
    lead_time_days: Mapped[int | None] = mapped_column()
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    product = relationship("Product", back_populates="supplier_products")
    prices = relationship(
        "SupplierPriceHistory",
        back_populates="supplier_product",
        cascade="all, delete-orphan",
    )


class SupplierPriceHistory(Base):
    """Append-only price history. Never overwrite, always insert new row."""

    __tablename__ = "supplier_price_history"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    supplier_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column()
    source: Mapped[str | None] = mapped_column(String(32))  # manual, catalog_import, ...
    notes: Mapped[str | None] = mapped_column(Text)

    supplier_product = relationship("SupplierProduct", back_populates="prices")
