"""Quotes — CRUD + line items + totals calculation."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id, get_current_user
from app.db.models.quote import Quote, QuoteLineItem
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class LineItemCreate(BaseModel):
    description: str
    quantity: Decimal
    unit: str = "pcs"
    unit_price: Decimal
    unit_cost: Decimal | None = None
    discount_pct: Decimal = Decimal("0")
    tax_rate: Decimal | None = None
    notes: str | None = None


class LineItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    position: int
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    unit_cost: Decimal | None = None
    discount_pct: Decimal
    tax_rate: Decimal | None = None
    line_total: Decimal | None = None
    margin_pct: Decimal | None = None
    notes: str | None = None


class QuoteCreate(BaseModel):
    project_id: UUID
    currency: str = "EUR"
    valid_until: date | None = None
    payment_terms: str | None = None
    notes_internal: str | None = None
    notes_external: str | None = None


class QuoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    version: int
    status: str
    currency: str
    subtotal: Decimal | None = None
    discount_total: Decimal
    tax_total: Decimal | None = None
    total: Decimal | None = None
    margin_pct: Decimal | None = None
    valid_until: date | None = None
    payment_terms: str | None = None
    notes_internal: str | None = None
    notes_external: str | None = None
    created_at: datetime
    line_items: list[LineItemResponse] = []


class QuoteUpdate(BaseModel):
    status: str | None = None
    currency: str | None = None
    valid_until: date | None = None
    payment_terms: str | None = None
    notes_internal: str | None = None
    notes_external: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _recalculate(quote: Quote) -> None:
    """Deterministični izračun totala iz line itemsa. Nikad LLM."""
    subtotal = Decimal("0")
    cost_total = Decimal("0")
    tax_total = Decimal("0")

    for i, item in enumerate(sorted(quote.line_items, key=lambda x: x.position), 1):
        item.position = i
        qty = item.quantity
        price = item.unit_price
        disc = item.discount_pct or Decimal("0")
        net_price = price * (1 - disc)
        line = (qty * net_price).quantize(Decimal("0.01"))
        item.line_total = line
        subtotal += line

        if item.unit_cost:
            cost = (qty * item.unit_cost).quantize(Decimal("0.01"))
            cost_total += cost
            if line > 0:
                item.margin_pct = ((line - cost) / line).quantize(Decimal("0.0001"))

        if item.tax_rate:
            tax_total += (line * item.tax_rate).quantize(Decimal("0.01"))

    quote.subtotal = subtotal
    quote.cost_total = cost_total if cost_total else None
    quote.tax_total = tax_total
    quote.total = (subtotal + tax_total).quantize(Decimal("0.01"))
    if cost_total and subtotal > 0:
        quote.margin_pct = ((subtotal - cost_total) / subtotal).quantize(Decimal("0.0001"))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[QuoteResponse])
async def list_quotes(
    project_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> list[QuoteResponse]:
    q = select(Quote).where(Quote.org_id == org_id).options(selectinload(Quote.line_items))
    if project_id:
        q = q.where(Quote.project_id == project_id)
    result = await db.execute(q.order_by(Quote.created_at.desc()))
    quotes = result.scalars().all()
    return [QuoteResponse.model_validate(qt) for qt in quotes]


@router.post("/", response_model=QuoteResponse, status_code=status.HTTP_201_CREATED)
async def create_quote(
    req: QuoteCreate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(get_current_user),
) -> QuoteResponse:
    # Sljedeći version broj za ovaj projekt
    existing = await db.execute(
        select(Quote.version).where(
            Quote.project_id == req.project_id, Quote.org_id == org_id
        ).order_by(Quote.version.desc()).limit(1)
    )
    last_version = existing.scalar_one_or_none() or 0

    quote = Quote(
        org_id=org_id,
        project_id=req.project_id,
        version=last_version + 1,
        currency=req.currency,
        valid_until=req.valid_until,
        payment_terms=req.payment_terms,
        notes_internal=req.notes_internal,
        notes_external=req.notes_external,
        status="draft",
        created_by=current_user.id,
        discount_total=Decimal("0"),
    )
    db.add(quote)
    await db.commit()
    await db.refresh(quote)
    return QuoteResponse.model_validate(quote)


@router.get("/{quote_id}", response_model=QuoteResponse)
async def get_quote(
    quote_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> QuoteResponse:
    result = await db.execute(
        select(Quote)
        .where(Quote.id == quote_id, Quote.org_id == org_id)
        .options(selectinload(Quote.line_items))
    )
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Ponuda nije pronađena.")
    return QuoteResponse.model_validate(quote)


@router.patch("/{quote_id}", response_model=QuoteResponse)
async def update_quote(
    quote_id: UUID,
    req: QuoteUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> QuoteResponse:
    result = await db.execute(
        select(Quote)
        .where(Quote.id == quote_id, Quote.org_id == org_id)
        .options(selectinload(Quote.line_items))
    )
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Ponuda nije pronađena.")
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(quote, field, value)
    await db.commit()
    await db.refresh(quote)
    return QuoteResponse.model_validate(quote)


@router.post("/{quote_id}/line-items", response_model=QuoteResponse, status_code=status.HTTP_201_CREATED)
async def add_line_item(
    quote_id: UUID,
    req: LineItemCreate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> QuoteResponse:
    result = await db.execute(
        select(Quote)
        .where(Quote.id == quote_id, Quote.org_id == org_id)
        .options(selectinload(Quote.line_items))
    )
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Ponuda nije pronađena.")

    position = max((li.position for li in quote.line_items), default=0) + 1
    item = QuoteLineItem(
        quote_id=quote.id,
        position=position,
        description=req.description,
        quantity=req.quantity,
        unit=req.unit,
        unit_price=req.unit_price,
        unit_cost=req.unit_cost,
        discount_pct=req.discount_pct,
        tax_rate=req.tax_rate,
        notes=req.notes,
    )
    db.add(item)
    quote.line_items.append(item)
    _recalculate(quote)
    await db.commit()
    await db.refresh(quote)
    return QuoteResponse.model_validate(quote)


@router.delete("/{quote_id}/line-items/{item_id}", response_model=QuoteResponse)
async def delete_line_item(
    quote_id: UUID,
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> QuoteResponse:
    result = await db.execute(
        select(Quote)
        .where(Quote.id == quote_id, Quote.org_id == org_id)
        .options(selectinload(Quote.line_items))
    )
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Ponuda nije pronađena.")
    item = next((li for li in quote.line_items if li.id == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Stavka nije pronađena.")
    quote.line_items.remove(item)
    await db.delete(item)
    _recalculate(quote)
    await db.commit()
    await db.refresh(quote)
    return QuoteResponse.model_validate(quote)


@router.delete("/{quote_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quote(
    quote_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> None:
    result = await db.execute(
        select(Quote).where(Quote.id == quote_id, Quote.org_id == org_id)
    )
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Ponuda nije pronađena.")
    await db.delete(quote)
    await db.commit()
