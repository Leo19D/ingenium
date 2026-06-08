"""Document upload, listing, and deletion."""

from __future__ import annotations

import contextlib
import hashlib
import uuid as uuid_module
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id, get_current_user
from app.db.models.document import Document, DocumentExtraction
from app.db.models.project import Project
from app.db.models.quote import Quote, QuoteLineItem
from app.db.models.user import User
from app.db.session import get_db
from app.services.ingestion.pipeline import parse_document

router = APIRouter()

UPLOAD_DIR = Path("uploads")
ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",  # generic binary — fallback, validated by extension
}
ALLOWED_EXT = {".pdf", ".xlsx", ".xls", ".csv", ".docx", ".doc"}
MAX_SIZE_MB = 25


def _resolve_mime(filename: str, declared_mime: str) -> str:
    """Return best-guess MIME, falling back to extension if declared is generic."""
    ext = Path(filename).suffix.lower()
    ext_map = {
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls":  "application/vnd.ms-excel",
        ".csv":  "text/csv",
        ".pdf":  "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc":  "application/msword",
    }
    if declared_mime in ("application/octet-stream", "", None):
        return ext_map.get(ext, declared_mime)
    return declared_mime


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    filename: str
    mime_type: str | None = None
    size_bytes: int | None = None
    status: str
    source: str | None = None
    project_id: UUID | None = None
    created_at: str = ""

    @classmethod
    def from_doc(cls, d: Document) -> DocumentResponse:
        return cls(
            id=d.id,
            filename=d.filename,
            mime_type=d.mime_type,
            size_bytes=d.size_bytes,
            status=d.status,
            source=d.source,
            project_id=d.project_id,
            created_at=d.created_at.isoformat() if d.created_at else "",
        )


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> list[DocumentResponse]:
    result = await db.execute(
        select(Document).where(Document.org_id == org_id).order_by(Document.created_at.desc())
    )
    return [DocumentResponse.from_doc(d) for d in result.scalars().all()]


@router.post("/upload", status_code=status.HTTP_201_CREATED, response_model=DocumentResponse)
async def upload_document(
    file: Annotated[UploadFile, File()],
    project_id: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    """Upload PDF, XLSX, CSV, DOCX dokumenta."""
    content = await file.read()
    size = len(content)

    if size > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Fajl je prevelik. Maksimum je {MAX_SIZE_MB} MB.",
        )

    ext = Path(file.filename or "").suffix.lower()
    mime = _resolve_mime(file.filename or "", file.content_type or "")
    if mime not in ALLOWED_MIME or ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Tip fajla nije podržan. Dozvoljeni: PDF, XLSX, XLS, CSV, DOCX.",
        )

    checksum = hashlib.sha256(content).hexdigest()
    file_id = uuid_module.uuid4()
    suffix = Path(file.filename or "upload").suffix or ".bin"
    storage_key = f"{org_id}_{file_id}{suffix}"

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / storage_key).write_bytes(content)

    proj_id: UUID | None = None
    if project_id:
        with contextlib.suppress(ValueError):
            proj_id = UUID(project_id)

    doc = Document(
        org_id=org_id,
        project_id=proj_id,
        uploaded_by=current_user.id,
        storage_key=storage_key,
        filename=file.filename or "upload",
        mime_type=mime,
        size_bytes=size,
        checksum=checksum,
        source="upload",
        status="received",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return DocumentResponse.from_doc(doc)


@router.post("/{doc_id}/parse")
async def trigger_parse(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> dict:
    """Parsira dokument i pokreće catalog matching. Vraća extraction s rezultatima."""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Dokument nije pronađen.")
    if doc.status == "parsed":
        # Vrati postojeću ekstrakciju
        ext_result = await db.execute(
            select(DocumentExtraction).where(DocumentExtraction.document_id == doc_id)
        )
        ext = ext_result.scalar_one_or_none()
        if ext and ext.structured_data:
            return {"status": "already_parsed", "extraction": ext.structured_data,
                    "confidence": float(ext.confidence or 0), "needs_review": ext.needs_review}

    doc.status = "parsing"
    await db.commit()

    try:
        extraction = await parse_document(db=db, document=doc, org_id=org_id)
    except Exception as e:
        doc.status = "failed"
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Parsiranje nije uspjelo: {e}") from e

    return {
        "status": "parsed",
        "extraction": extraction.structured_data,
        "confidence": float(extraction.confidence or 0),
        "needs_review": extraction.needs_review,
    }


@router.get("/{doc_id}/extraction")
async def get_extraction(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> dict:
    """Vrati rezultate parsiranja za dokument."""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Dokument nije pronađen.")

    ext_result = await db.execute(
        select(DocumentExtraction).where(DocumentExtraction.document_id == doc_id)
    )
    ext = ext_result.scalar_one_or_none()
    if not ext:
        raise HTTPException(status_code=404, detail="Dokument nije još parsiran. Pokreni /parse.")

    return {
        "document_id": str(doc_id),
        "filename": doc.filename,
        "status": doc.status,
        "confidence": float(ext.confidence or 0),
        "needs_review": ext.needs_review,
        "extraction": ext.structured_data,
    }


class CreateQuoteFromDocRequest(BaseModel):
    project_name: str = Field(min_length=1)
    client_id: UUID | None = None
    currency: str = "EUR"
    # Marža 0..0.95 — formula cost/(1-margin) puca na margin>=1 (dijeljenje s nulom)
    margin_pct: float = Field(default=0.25, ge=0, le=0.95)
    selected_items: list[dict] | None = None


@router.post("/{doc_id}/create-quote", status_code=status.HTTP_201_CREATED)
async def create_quote_from_document(
    doc_id: UUID,
    req: CreateQuoteFromDocRequest,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Kreira projekt + ponudu iz parsiranog dokumenta."""
    from decimal import Decimal

    doc_result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.org_id == org_id)
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Dokument nije pronađen.")

    ext_result = await db.execute(
        select(DocumentExtraction).where(DocumentExtraction.document_id == doc_id)
    )
    ext = ext_result.scalar_one_or_none()
    if not ext or not ext.structured_data:
        raise HTTPException(status_code=422, detail="Pokrenite parsiranje dokumenta prije kreiranja ponude.")

    items = req.selected_items or ext.structured_data.get("line_items", [])
    if not items:
        raise HTTPException(status_code=422, detail="Nema stavki za kreiranje ponude.")

    # Kreiraj projekt
    project = Project(
        org_id=org_id,
        name=req.project_name,
        client_id=req.client_id,
        status="quoting",
    )
    db.add(project)
    await db.flush()

    # Kreiraj ponudu
    quote = Quote(
        org_id=org_id,
        project_id=project.id,
        version=1,
        currency=req.currency,
        status="draft",
        discount_total=Decimal("0"),
        created_by=current_user.id,
    )
    db.add(quote)
    await db.flush()

    # Dodaj stavke s maržom
    subtotal = Decimal("0")
    for pos, item in enumerate(items, 1):
        desc = item.get("description", "")
        qty  = Decimal(str(item.get("quantity") or 1))
        unit = item.get("unit", "pcs")

        # Nabavna cijena iz matched stock itema ili iz dokumenta
        match = item.get("accepted_match") or (
            item.get("match_candidates", [{}])[0] if item.get("match_candidates") else {}
        )
        unit_cost = Decimal(str(match.get("unit_cost") or item.get("unit_price") or 0))

        # Prodajna cijena = nabavna / (1 - marža). Guard: margin u [0, 0.95]
        margin = max(Decimal("0"), min(Decimal(str(req.margin_pct)), Decimal("0.95")))
        unit_price = (unit_cost / (1 - margin)).quantize(Decimal("0.01")) if unit_cost > 0 else Decimal("0")

        line_total = (qty * unit_price).quantize(Decimal("0.01"))
        subtotal += line_total

        # Veza na skladišnu stavku iz matchinga → omogućuje skidanje zalihe kad ponuda prođe
        stock_item_id = None
        raw_sid = match.get("stock_item_id")
        if raw_sid:
            try:
                stock_item_id = UUID(str(raw_sid))
            except (ValueError, TypeError):
                stock_item_id = None

        li = QuoteLineItem(
            quote_id=quote.id,
            position=pos,
            description=desc,
            quantity=qty,
            unit=unit,
            stock_item_id=stock_item_id,
            unit_cost=unit_cost if unit_cost > 0 else None,
            unit_price=unit_price,
            discount_pct=Decimal("0"),
            line_total=line_total,
            margin_pct=margin if unit_cost > 0 else None,
        )
        db.add(li)

    quote.subtotal = subtotal
    quote.total = subtotal
    quote.margin_pct = Decimal(str(req.margin_pct))

    # Poveži dokument s projektom
    doc.project_id = project.id

    await db.commit()

    return {
        "project_id": str(project.id),
        "quote_id": str(quote.id),
        "item_count": len(items),
        "total": float(subtotal),
        "currency": req.currency,
        "margin_pct": req.margin_pct,
        "message": f"Ponuda kreirana s {len(items)} stavki iz dokumenta '{doc.filename}'",
    }


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> None:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Dokument nije pronađen.")
    local = UPLOAD_DIR / doc.storage_key
    if local.exists():
        local.unlink()
    await db.delete(doc)
    await db.commit()
