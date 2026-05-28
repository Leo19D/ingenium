"""Suppliers API endpoints — CRUD + bulk import iz Excela."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.api.v1.clients import _normalize_country_code, _parse_int
from app.db.models.supplier import Supplier
from app.db.session import get_db
from app.schemas.client import BulkImportResult
from app.schemas.supplier import (
    SupplierBulkImportRequest,
    SupplierCreate,
    SupplierResponse,
    SupplierUpdate,
)

router = APIRouter()


@router.get("/", response_model=list[SupplierResponse])
async def list_suppliers(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> list[Supplier]:
    result = await db.execute(
        select(Supplier)
        .where(Supplier.org_id == org_id)
        .order_by(Supplier.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{supplier_id}", response_model=SupplierResponse)
async def get_supplier(
    supplier_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> Supplier:
    result = await db.execute(
        select(Supplier).where(Supplier.id == supplier_id, Supplier.org_id == org_id)
    )
    supplier = result.scalar_one_or_none()
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dobavljač ne postoji")
    return supplier


@router.post("/", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    payload: SupplierCreate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> Supplier:
    supplier = Supplier(org_id=org_id, **payload.model_dump())
    db.add(supplier)
    await db.flush()
    await db.refresh(supplier)
    return supplier


@router.patch("/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(
    supplier_id: UUID,
    payload: SupplierUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> Supplier:
    result = await db.execute(
        select(Supplier).where(Supplier.id == supplier_id, Supplier.org_id == org_id)
    )
    supplier = result.scalar_one_or_none()
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dobavljač ne postoji")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(supplier, k, v)
    await db.flush()
    await db.refresh(supplier)
    return supplier


@router.delete("/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_supplier(
    supplier_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> None:
    result = await db.execute(
        select(Supplier).where(Supplier.id == supplier_id, Supplier.org_id == org_id)
    )
    supplier = result.scalar_one_or_none()
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dobavljač ne postoji")
    await db.delete(supplier)


@router.post("/bulk", response_model=BulkImportResult, status_code=status.HTTP_201_CREATED)
async def bulk_import_suppliers(
    payload: SupplierBulkImportRequest,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> BulkImportResult:
    inserted = 0
    skipped = 0
    errors: list[str] = []

    for idx, item in enumerate(payload.items):
        try:
            if not item.naziv or not item.naziv.strip():
                skipped += 1
                continue
            supplier = Supplier(
                org_id=org_id,
                name=item.naziv.strip(),
                country_code=_normalize_country_code(item.country),
                currency=(item.currency or "EUR").upper().strip(),
                incoterms_default=(item.incoterms or "EXW").upper().strip(),
                lead_time_days_avg=_parse_int(item.lead, 0) or None,
            )
            db.add(supplier)
            await db.flush()
            inserted += 1
        except IntegrityError:
            await db.rollback()
            skipped += 1
        except Exception as e:  # noqa: BLE001
            await db.rollback()
            errors.append(f"Red {idx + 1}: {type(e).__name__}: {e}")
            skipped += 1

    return BulkImportResult(inserted=inserted, skipped=skipped, errors=errors)
