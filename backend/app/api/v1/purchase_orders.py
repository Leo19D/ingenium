"""Narudžbenice (purchase orders) — nabava od dobavljača + primka u skladište."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_org_id, get_current_user, require_role
from app.db.models.procurement import PO_STATUSES, PurchaseOrder, PurchaseOrderLine
from app.db.models.quote import Quote
from app.db.models.user import User
from app.db.session import get_db
from app.services.audit import log_action
from app.services.inventory import apply_movement

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────

class POLineIn(BaseModel):
    description: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    unit: str = "pcs"
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0)
    sku: str | None = None
    stock_item_id: UUID | None = None


class POCreate(BaseModel):
    supplier_id: UUID | None = None
    currency: str = "EUR"
    notes: str | None = None
    expected_date: date | None = None
    lines: list[POLineIn] = Field(min_length=1)


class POUpdate(BaseModel):
    supplier_id: UUID | None = None
    status: str | None = None
    notes: str | None = None
    expected_date: date | None = None


class POLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    stock_item_id: UUID | None = None
    sku: str | None = None
    description: str
    quantity: Decimal
    unit: str
    unit_cost: Decimal
    line_total: Decimal | None = None


class POResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    po_number: str
    supplier_id: UUID | None = None
    quote_id: UUID | None = None
    status: str
    currency: str
    subtotal: Decimal | None = None
    total: Decimal | None = None
    notes: str | None = None
    expected_date: date | None = None
    sent_at: datetime | None = None
    received_at: datetime | None = None
    created_at: datetime
    lines: list[POLineOut] = []


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _next_po_number(db: AsyncSession, org_id: UUID) -> str:
    year = datetime.now(UTC).year
    n = await db.scalar(
        select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.org_id == org_id)
    )
    return f"PO-{year}-{(n or 0) + 1:04d}"


def _recalc(po: PurchaseOrder) -> None:
    subtotal = Decimal("0")
    for ln in po.lines:
        ln.line_total = (ln.quantity * ln.unit_cost).quantize(Decimal("0.01"))
        subtotal += ln.line_total
    po.subtotal = subtotal
    po.total = subtotal


async def _get_po(db: AsyncSession, po_id: UUID, org_id: UUID) -> PurchaseOrder:
    po = (await db.execute(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == po_id, PurchaseOrder.org_id == org_id)
        .options(selectinload(PurchaseOrder.lines))
    )).scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="Narudžbenica nije pronađena.")
    return po


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[POResponse])
async def list_pos(
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> list[PurchaseOrder]:
    q = (
        select(PurchaseOrder)
        .where(PurchaseOrder.org_id == org_id)
        .options(selectinload(PurchaseOrder.lines))
        .order_by(PurchaseOrder.created_at.desc())
    )
    if status_filter:
        q = q.where(PurchaseOrder.status == status_filter)
    return list((await db.execute(q)).scalars().all())


@router.get("/{po_id}", response_model=POResponse)
async def get_po(
    po_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> PurchaseOrder:
    return await _get_po(db, po_id, org_id)


@router.post("/", response_model=POResponse, status_code=status.HTTP_201_CREATED)
async def create_po(
    req: POCreate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(get_current_user),
    _: str = Depends(require_role("procurement")),
) -> PurchaseOrder:
    po = PurchaseOrder(
        org_id=org_id,
        supplier_id=req.supplier_id,
        po_number=await _next_po_number(db, org_id),
        status="draft",
        currency=req.currency.upper()[:3],
        notes=req.notes,
        expected_date=req.expected_date,
        created_by=current_user.id,
    )
    po.lines = [
        PurchaseOrderLine(
            description=ln.description, quantity=ln.quantity, unit=ln.unit,
            unit_cost=ln.unit_cost, sku=ln.sku, stock_item_id=ln.stock_item_id,
        )
        for ln in req.lines
    ]
    _recalc(po)
    db.add(po)
    await db.commit()
    await db.refresh(po, attribute_names=["lines"])
    await log_action(db, org_id=org_id, user_id=current_user.id, action="po.created",
                     entity_type="purchase_order", entity_id=po.id)
    return po


@router.post("/from-quote/{quote_id}", response_model=POResponse, status_code=status.HTTP_201_CREATED)
async def create_po_from_quote(
    quote_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(get_current_user),
    _: str = Depends(require_role("procurement")),
) -> PurchaseOrder:
    """Generiraj nacrt narudžbenice iz stavki ponude (nabavna cijena = unit_cost)."""
    quote = (await db.execute(
        select(Quote).where(Quote.id == quote_id, Quote.org_id == org_id)
        .options(selectinload(Quote.line_items))
    )).scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Ponuda nije pronađena.")
    if not quote.line_items:
        raise HTTPException(status_code=422, detail="Ponuda nema stavki.")

    po = PurchaseOrder(
        org_id=org_id, quote_id=quote_id,
        po_number=await _next_po_number(db, org_id),
        status="draft", currency=quote.currency,
        notes=f"Iz ponude V{quote.version}", created_by=current_user.id,
    )
    po.lines = [
        PurchaseOrderLine(
            description=li.description, quantity=li.quantity, unit=li.unit,
            unit_cost=li.unit_cost or Decimal("0"), stock_item_id=li.stock_item_id,
        )
        for li in sorted(quote.line_items, key=lambda x: x.position)
    ]
    _recalc(po)
    db.add(po)
    await db.commit()
    await db.refresh(po, attribute_names=["lines"])
    await log_action(db, org_id=org_id, user_id=current_user.id, action="po.created_from_quote",
                     entity_type="purchase_order", entity_id=po.id, after_state={"quote_id": str(quote_id)})
    return po


@router.post(
    "/from-quote/{quote_id}/grouped",
    response_model=list[POResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_pos_from_quote_grouped(
    quote_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(get_current_user),
    _: str = Depends(require_role("procurement")),
) -> list[PurchaseOrder]:
    """Generiraj narudžbenice iz ponude — JEDNA po dobavljaču.

    Grupira stavke po dobavljaču (iz `supplier_product_id`). Stavke koje su na
    skladištu (samo `stock_item_id`, bez veze na dobavljača) se preskaču — njih
    ne treba naručivati. Vraća listu nacrta narudžbenica.
    """
    from app.db.models.product import SupplierProduct

    quote = (await db.execute(
        select(Quote).where(Quote.id == quote_id, Quote.org_id == org_id)
        .options(selectinload(Quote.line_items))
    )).scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Ponuda nije pronađena.")
    if not quote.line_items:
        raise HTTPException(status_code=422, detail="Ponuda nema stavki.")

    # Razriješi supplier_product_id → (supplier_id, supplier_sku)
    sp_ids = {li.supplier_product_id for li in quote.line_items if li.supplier_product_id}
    sp_map: dict[UUID, SupplierProduct] = {}
    if sp_ids:
        sps = (await db.execute(
            select(SupplierProduct).where(SupplierProduct.id.in_(sp_ids))
        )).scalars().all()
        sp_map = {sp.id: sp for sp in sps}

    # Grupiraj stavke po dobavljaču (samo one koje treba naručiti)
    by_supplier: dict[UUID, list] = {}
    for li in sorted(quote.line_items, key=lambda x: x.position):
        sp = sp_map.get(li.supplier_product_id) if li.supplier_product_id else None
        if not sp:
            continue  # na skladištu / bez dobavljača → ne naručuje se
        by_supplier.setdefault(sp.supplier_id, []).append((li, sp))

    if not by_supplier:
        raise HTTPException(
            status_code=422,
            detail="Nema stavki za naručiti — sve su na skladištu ili bez vezanog dobavljača.",
        )

    # Sekvencijalni brojevi (count se ne mijenja do commita → ručno inkrementiraj)
    year = datetime.now(UTC).year
    base = await db.scalar(
        select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.org_id == org_id)
    ) or 0

    pos: list[PurchaseOrder] = []
    for offset, (supplier_id, rows) in enumerate(by_supplier.items(), 1):
        po = PurchaseOrder(
            org_id=org_id, quote_id=quote_id, supplier_id=supplier_id,
            po_number=f"PO-{year}-{base + offset:04d}",
            status="draft", currency=quote.currency,
            notes=f"Iz ponude V{quote.version} (auto, po dobavljaču)",
            created_by=current_user.id,
        )
        po.lines = [
            PurchaseOrderLine(
                description=li.description, quantity=li.quantity, unit=li.unit,
                unit_cost=li.unit_cost or Decimal("0"),
                sku=sp.supplier_sku, stock_item_id=li.stock_item_id,
            )
            for li, sp in rows
        ]
        _recalc(po)
        db.add(po)
        pos.append(po)

    await db.commit()
    for po in pos:
        await db.refresh(po, attribute_names=["lines"])
    await log_action(
        db, org_id=org_id, user_id=current_user.id, action="po.created_from_quote_grouped",
        entity_type="purchase_order", entity_id=quote_id,
        after_state={"quote_id": str(quote_id), "po_count": len(pos)},
    )
    return pos


@router.patch("/{po_id}", response_model=POResponse)
async def update_po(
    po_id: UUID,
    req: POUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    _: str = Depends(require_role("procurement")),
) -> PurchaseOrder:
    po = await _get_po(db, po_id, org_id)
    if po.status == "received":
        raise HTTPException(status_code=409, detail="Zaprimljena narudžbenica se ne može mijenjati.")
    if req.status is not None:
        if req.status not in PO_STATUSES:
            raise HTTPException(status_code=422, detail=f"Status mora biti: {', '.join(PO_STATUSES)}")
        if req.status == "received":
            raise HTTPException(status_code=422, detail="Za zaprimanje koristi POST /{id}/receive.")
        if req.status == "sent" and po.status == "draft":
            po.sent_at = datetime.now(UTC)
        po.status = req.status
    if req.supplier_id is not None:
        po.supplier_id = req.supplier_id
    if req.notes is not None:
        po.notes = req.notes
    if req.expected_date is not None:
        po.expected_date = req.expected_date
    await db.commit()
    await db.refresh(po, attribute_names=["lines"])
    return po


@router.post("/{po_id}/receive", response_model=POResponse)
async def receive_po(
    po_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(get_current_user),
    _: str = Depends(require_role("procurement")),
) -> PurchaseOrder:
    """Zaprimi narudžbenicu → poveća zalihu za stavke vezane na skladište."""
    po = await _get_po(db, po_id, org_id)
    if po.status == "received":
        raise HTTPException(status_code=409, detail="Narudžbenica je već zaprimljena.")
    if po.status == "cancelled":
        raise HTTPException(status_code=409, detail="Otkazana narudžbenica se ne može zaprimiti.")

    received = 0
    for ln in po.lines:
        if ln.stock_item_id:
            updated = await apply_movement(
                db, org_id=org_id, stock_item_id=ln.stock_item_id,
                delta=ln.quantity, reason="po_receipt",
                ref_type="purchase_order", ref_id=po.id,
                note=f"Primka {po.po_number}",
            )
            if updated:
                received += 1
    po.status = "received"
    po.received_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(po, attribute_names=["lines"])
    await log_action(db, org_id=org_id, user_id=current_user.id, action="po.received",
                     entity_type="purchase_order", entity_id=po.id,
                     after_state={"stock_in_lines": received})
    return po


@router.delete("/{po_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_po(
    po_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    _: str = Depends(require_role("procurement")),
) -> None:
    po = await _get_po(db, po_id, org_id)
    if po.status == "received":
        raise HTTPException(status_code=409, detail="Zaprimljena narudžbenica se ne može obrisati.")
    await db.delete(po)
    await db.commit()
