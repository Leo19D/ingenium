"""
Document ingestion pipeline.
parse → extract line items → catalog matching → store DocumentExtraction
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document, DocumentExtraction
from app.services.ingestion.confidence import needs_review, score_line_item
from app.services.ingestion.normalizer import normalize_unit
from app.services.ingestion.parsers.pdf import PdfParser
from app.services.ingestion.parsers.xlsx import XlsxParser
from app.services.matching.catalog_matcher import MatchResult, match_item

logger = structlog.get_logger(__name__)

UPLOAD_DIR = Path("uploads")


def _to_decimal(val: object) -> Decimal | None:
    if val is None or str(val).strip() in ("", "None", "-", "—"):
        return None
    try:
        s = re.sub(r"[^\d.\-]", "", str(val).replace(",", ".").replace(" ", ""))
        return Decimal(s) if s else None
    except InvalidOperation:
        return None


def _extract_items_from_table(table, source_method: str) -> list[dict]:
    col_map: dict = getattr(table, "col_map", None) or {}
    rows = table.rows

    desc_col  = col_map.get("description")
    qty_col   = col_map.get("quantity")
    unit_col  = col_map.get("unit")
    price_col = col_map.get("unit_price")
    sku_col   = col_map.get("sku")

    items = []
    for pos, row in enumerate(rows, 1):
        def get(col):
            if col is None or col >= len(row):
                return None
            v = row[col]
            return v.strip() if v else None

        desc = get(desc_col)
        if not desc or len(desc) < 2:
            continue

        qty   = _to_decimal(get(qty_col))
        price = _to_decimal(get(price_col))
        unit  = normalize_unit(get(unit_col))
        sku   = get(sku_col)

        confidence = score_line_item(
            has_quantity=qty is not None,
            has_unit_price=price is not None,
            has_description=bool(desc),
            source_method=source_method,
            sum_check_ok=True,
        )

        items.append({
            "position": pos,
            "description": desc,
            "quantity": float(qty) if qty else None,
            "unit": unit,
            "unit_price": float(price) if price else None,
            "sku_hint": sku,
            "confidence": float(confidence),
            "needs_review": needs_review(confidence),
            "match_candidates": [],
            "accepted_match": None,
        })

    return items


async def parse_document(
    *,
    db: AsyncSession,
    document: Document,
    org_id: UUID,
) -> DocumentExtraction:
    log = logger.bind(document_id=str(document.id), filename=document.filename)
    log.info("ingestion_start")

    file_path = UPLOAD_DIR / document.storage_key
    if not file_path.exists():
        raise FileNotFoundError(f"Fajl ne postoji: {file_path}")

    file_bytes = file_path.read_bytes()
    mime = document.mime_type or ""

    if "sheet" in mime or "excel" in mime or document.filename.lower().endswith((".xlsx", ".xls")):
        parser = XlsxParser()
        source_method = "openpyxl"
    elif "pdf" in mime or document.filename.lower().endswith(".pdf"):
        parser = PdfParser()
        source_method = "pdfplumber"
    else:
        parser = XlsxParser()
        source_method = "openpyxl"

    parsed = await parser.parse(file_bytes, document.filename)
    log.info("parsing_done", tables=len(parsed.tables))

    all_items: list[dict] = []
    for table in parsed.tables:
        all_items.extend(_extract_items_from_table(table, source_method))

    log.info("extraction_done", items=len(all_items))

    # Catalog matching
    for item in all_items:
        try:
            result: MatchResult = await match_item(
                db=db,
                org_id=org_id,
                description=item["description"],
                sku_hint=item.get("sku_hint"),
            )
            item["match_candidates"] = [
                {
                    "stock_item_id": str(c.stock_item_id),
                    "sku": c.sku,
                    "name": c.name,
                    "unit_cost": float(c.unit_cost) if c.unit_cost else None,
                    "quantity_on_hand": float(c.quantity_on_hand),
                    "score": c.score,
                    "method": c.match_method,
                }
                for c in result.candidates
            ]
            item["accepted_match"] = (
                {
                    "stock_item_id": str(result.accepted.stock_item_id),
                    "sku": result.accepted.sku,
                    "name": result.accepted.name,
                    "unit_cost": float(result.accepted.unit_cost) if result.accepted.unit_cost else None,
                }
                if result.accepted else None
            )
        except Exception as e:
            log.warning("match_error", desc=item["description"], err=str(e))

    confidences = [i["confidence"] for i in all_items]
    overall = sum(confidences) / len(confidences) if confidences else 0.0
    doc_review = any(i["needs_review"] for i in all_items) or overall < 0.85

    extraction = DocumentExtraction(
        document_id=document.id,
        raw_text=parsed.raw_text[:30_000],
        structured_data={"line_items": all_items, "item_count": len(all_items), "source": source_method},
        extraction_method=source_method,
        confidence=Decimal(str(round(overall, 2))),
        needs_review=doc_review,
    )
    db.add(extraction)
    document.status = "parsed"
    document.detected_lang = parsed.detected_lang
    await db.commit()
    await db.refresh(extraction)

    log.info("ingestion_complete", items=len(all_items), confidence=overall)
    return extraction
