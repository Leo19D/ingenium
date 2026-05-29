"""Quotes — CRUD + line items + totals calculation + Excel export + historical import."""

from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id, get_current_user
from app.db.models.client import Client
from app.db.models.project import Project
from app.db.models.quote import Quote, QuoteLineItem, QuoteOutcome
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


# ── Quote outcome (won/lost) ──────────────────────────────────────────────────

class OutcomeCreate(BaseModel):
    outcome: str  # won, lost, withdrawn, expired, no_response
    reason: str | None = None
    competitor_name: str | None = None
    competitor_price: Decimal | None = None
    lessons: str | None = None


@router.post("/{quote_id}/outcome", status_code=status.HTTP_201_CREATED)
async def record_outcome(
    quote_id: UUID,
    req: OutcomeCreate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(get_current_user),
) -> dict:
    result = await db.execute(
        select(Quote).where(Quote.id == quote_id, Quote.org_id == org_id)
    )
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Ponuda nije pronađena.")

    existing = await db.execute(select(QuoteOutcome).where(QuoteOutcome.quote_id == quote_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Ishod za ovu ponudu već postoji.")

    valid = {"won", "lost", "withdrawn", "expired", "no_response"}
    if req.outcome not in valid:
        raise HTTPException(status_code=422, detail=f"Ishod mora biti jedan od: {', '.join(valid)}")

    outcome = QuoteOutcome(
        quote_id=quote_id,
        outcome=req.outcome,
        reason=req.reason,
        competitor_name=req.competitor_name,
        competitor_price=req.competitor_price,
        lessons=req.lessons,
        recorded_by=current_user.id,
    )
    db.add(outcome)
    quote.status = "accepted" if req.outcome == "won" else "rejected" if req.outcome == "lost" else req.outcome
    await db.commit()
    return {"message": "Ishod zabilježen.", "outcome": req.outcome}


# ── Quote → Excel export ──────────────────────────────────────────────────────

@router.get("/{quote_id}/export/xlsx")
async def export_quote_xlsx(
    quote_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> StreamingResponse:
    """Generiraj klijent-spreman Excel dokument ponude."""
    result = await db.execute(
        select(Quote)
        .where(Quote.id == quote_id, Quote.org_id == org_id)
        .options(selectinload(Quote.line_items))
    )
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Ponuda nije pronađena.")

    # Dohvati naziv projekta i klijenta
    proj_result = await db.execute(select(Project).where(Project.id == quote.project_id))
    project = proj_result.scalar_one_or_none()
    client_name = ""
    if project and project.client_id:
        cl_result = await db.execute(select(Client).where(Client.id == project.client_id))
        cl = cl_result.scalar_one_or_none()
        if cl:
            client_name = cl.name

    wb = Workbook()
    ws = wb.active
    ws.title = "Ponuda"

    # Stilovi
    dark_fill  = PatternFill("solid", fgColor="0C1410")
    green_fill = PatternFill("solid", fgColor="1E3A2A")
    head_font  = Font(bold=True, color="A8F4B8", name="Calibri", size=11)
    title_font = Font(bold=True, color="DDEADF", name="Calibri", size=14)
    sub_font   = Font(color="7A9480", name="Calibri", size=9)
    body_font  = Font(color="DDEADF", name="Calibri", size=10)
    mono_font  = Font(color="A8F4B8", name="Courier New", size=10)
    thin = Side(style="thin", color="1E3A2A")
    border = Border(bottom=Side(style="thin", color="1E3A2A"))

    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = "A8F4B8"

    # Header – branding
    ws.merge_cells("A1:H1")
    ws["A1"] = "⚡  INGENIUM"
    ws["A1"].font = Font(bold=True, color="A8F4B8", name="Calibri", size=16)
    ws["A1"].fill = dark_fill
    ws.row_dimensions[1].height = 32

    ws.merge_cells("A2:H2")
    ws["A2"] = "AI Quote & Procurement Platform  ·  ingeniumtrade.hr"
    ws["A2"].font = sub_font
    ws["A2"].fill = dark_fill

    # Separator
    ws.merge_cells("A3:H3")
    ws["A3"].fill = PatternFill("solid", fgColor="A8F4B8")
    ws.row_dimensions[3].height = 3

    # Metadata blok
    meta = [
        ("Ponuda br.",  f"V{quote.version}"),
        ("Projekt",     project.name if project else "—"),
        ("Klijent",     client_name or "—"),
        ("Valuta",      quote.currency),
        ("Vrijedi do",  str(quote.valid_until) if quote.valid_until else "—"),
        ("Uvjeti",      quote.payment_terms or "—"),
    ]
    for i, (label, value) in enumerate(meta, 5):
        ws.cell(row=i, column=1, value=label).font = sub_font
        ws.cell(row=i, column=1).fill = dark_fill
        cell = ws.cell(row=i, column=2, value=value)
        cell.font = body_font
        cell.fill = dark_fill
        ws.row_dimensions[i].height = 18

    ws.row_dimensions[4].height = 8  # razmak

    # Line items header
    header_row = len(meta) + 6
    col_labels = ["#", "Opis", "Količina", "Jed.", "Cijena/jed.", "Popust", "Porez", "Ukupno"]
    for col, label in enumerate(col_labels, 1):
        cell = ws.cell(row=header_row, column=col, value=label)
        cell.fill = green_fill
        cell.font = head_font
        cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[header_row].height = 22

    # Line items
    items = sorted(quote.line_items, key=lambda x: x.position)
    for r, item in enumerate(items, header_row + 1):
        row_fill = PatternFill("solid", fgColor="0A100E") if r % 2 == 0 else dark_fill
        vals = [
            item.position,
            item.description,
            float(item.quantity),
            item.unit,
            float(item.unit_price),
            f"{float(item.discount_pct or 0)*100:.1f}%",
            f"{float(item.tax_rate or 0)*100:.1f}%" if item.tax_rate else "—",
            float(item.line_total or 0),
        ]
        for col, val in enumerate(vals, 1):
            cell = ws.cell(row=r, column=col, value=val)
            cell.fill = row_fill
            cell.font = mono_font if col in (1, 3, 5, 8) else body_font
            if col == 8:  # ukupno
                cell.number_format = f'"{quote.currency}" #,##0.00'
            if col == 5:
                cell.number_format = f'"{quote.currency}" #,##0.0000'
        ws.row_dimensions[r].height = 18

    # Totals
    total_row = header_row + len(items) + 2
    ws.merge_cells(f"A{total_row}:F{total_row}")
    for label, value, col in [
        ("Međuzbroj",  quote.subtotal,       7),
        ("Porez",      quote.tax_total,      7),
    ]:
        ws.cell(row=total_row, column=6, value=label).font = sub_font
        ws.cell(row=total_row, column=6).fill = dark_fill
        ws.cell(row=total_row, column=7, value=float(value or 0)).font = body_font
        ws.cell(row=total_row, column=7).number_format = f'"{quote.currency}" #,##0.00'
        ws.cell(row=total_row, column=7).fill = dark_fill
        total_row += 1

    # Grand total row
    ws.cell(row=total_row, column=6, value="UKUPNO").font = Font(bold=True, color="A8F4B8", name="Calibri", size=11)
    ws.cell(row=total_row, column=6).fill = green_fill
    ws.cell(row=total_row, column=7, value=float(quote.total or 0)).font = Font(bold=True, color="A8F4B8", name="Calibri", size=11)
    ws.cell(row=total_row, column=7).fill = green_fill
    ws.cell(row=total_row, column=7).number_format = f'"{quote.currency}" #,##0.00'
    ws.row_dimensions[total_row].height = 24

    # Napomene
    if quote.notes_external:
        note_row = total_row + 2
        ws.merge_cells(f"A{note_row}:H{note_row}")
        ws.cell(row=note_row, column=1, value="Napomena: " + quote.notes_external).font = sub_font
        ws.cell(row=note_row, column=1).fill = dark_fill

    # Column widths
    col_widths = [5, 45, 10, 7, 13, 9, 9, 14]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Freeze header
    ws.freeze_panes = f"A{header_row + 1}"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"ponuda-V{quote.version}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Historical quotes import (won/lost trening data) ─────────────────────────

class HistoricalImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str]


@router.post("/import-historical", response_model=HistoricalImportResult)
async def import_historical_quotes(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(get_current_user),
) -> HistoricalImportResult:
    """
    Uvoz historijskih ponuda iz Excela za AI trening.
    Kolone: naziv_projekta | klijent | datum | valuta | total | marza_pct | ishod | razlog | konkurent | cijena_konkurenta
    """
    content = await file.read()
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
    except Exception:
        raise HTTPException(status_code=422, detail="Neispravan Excel fajl.")

    rows = list(ws.iter_rows(min_row=2, values_only=True))
    imported = 0
    skipped = 0
    errors: list[str] = []
    OUTCOME_MAP = {"won": "won", "lost": "lost", "pobijedio": "won", "izgubio": "lost",
                   "povučeno": "withdrawn", "isteklo": "expired", "nema odgovora": "no_response"}

    for i, row in enumerate(rows, 2):
        if not row or not any(row):
            skipped += 1
            continue
        try:
            project_name = str(row[0]).strip() if row[0] else f"Historijski projekt {i}"
            total_raw = row[4]
            margin_raw = row[5]
            outcome_raw = str(row[6]).strip().lower() if len(row) > 6 and row[6] else "no_response"
            outcome = OUTCOME_MAP.get(outcome_raw, "no_response")
            total = Decimal(str(total_raw).replace(",", ".")) if total_raw else Decimal("0")
            margin = Decimal(str(margin_raw).replace(",", ".").replace("%", "")) if margin_raw else None
            if margin and margin > 1:  # pretvorba ako je kao postotak npr. 25 umjesto 0.25
                margin = margin / 100

            # Kreiraj dummy projekt
            project = Project(org_id=org_id, name=project_name, status="won" if outcome == "won" else "lost")
            db.add(project)
            await db.flush()

            # Kreiraj dummy quote
            quote = Quote(
                org_id=org_id,
                project_id=project.id,
                version=1,
                currency=str(row[3]).strip().upper() if len(row) > 3 and row[3] else "EUR",
                status="accepted" if outcome == "won" else "rejected",
                total=total,
                subtotal=total,
                margin_pct=margin,
                discount_total=Decimal("0"),
                created_by=current_user.id,
            )
            db.add(quote)
            await db.flush()

            # Kreiraj outcome zapis (ključan za AI)
            qo = QuoteOutcome(
                quote_id=quote.id,
                outcome=outcome,
                reason=str(row[7]).strip() if len(row) > 7 and row[7] else None,
                competitor_name=str(row[8]).strip() if len(row) > 8 and row[8] else None,
                competitor_price=Decimal(str(row[9]).replace(",", ".")) if len(row) > 9 and row[9] else None,
                recorded_by=current_user.id,
            )
            db.add(qo)
            imported += 1
        except Exception as e:
            errors.append(f"Red {i}: {e}")
            skipped += 1

    await db.commit()
    return HistoricalImportResult(imported=imported, skipped=skipped, errors=errors[:10])
