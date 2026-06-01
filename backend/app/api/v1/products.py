"""Products catalog — CRUD."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.db.models.product import Product
from app.db.session import get_db

router = APIRouter()


class ProductCreate(BaseModel):
    sku: str
    name: str
    description: str | None = None
    category: str | None = None
    brand: str | None = None
    unit: str = "pcs"


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sku: str
    name: str
    description: str | None = None
    category: str | None = None
    brand: str | None = None
    unit: str
    is_active: bool


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    brand: str | None = None
    unit: str | None = None
    is_active: bool | None = None


@router.get("/", response_model=list[ProductResponse])
async def list_products(
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> list[Product]:
    q = select(Product).where(Product.org_id == org_id, Product.is_active == True)
    if category:
        q = q.where(Product.category == category)
    result = await db.execute(q.order_by(Product.name))
    return list(result.scalars().all())


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    req: ProductCreate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> Product:
    product = Product(
        org_id=org_id,
        sku=req.sku.strip(),
        name=req.name.strip(),
        description=req.description,
        category=req.category,
        brand=req.brand,
        unit=req.unit,
        is_active=True,
    )
    db.add(product)
    try:
        await db.commit()
        await db.refresh(product)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"SKU '{req.sku}' već postoji.")
    return product


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> Product:
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.org_id == org_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Artikal nije pronađen.")
    return product


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID,
    req: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> Product:
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.org_id == org_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Artikal nije pronađen.")
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(product, field, value)
    await db.commit()
    await db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> None:
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.org_id == org_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Artikal nije pronađen.")
    await db.delete(product)
    await db.commit()
