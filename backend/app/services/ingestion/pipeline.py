"""
Document ingestion pipeline.

Flow:
  1. Parse file (xlsx/pdf) → raw tables
  2. Heuristic extraction → line items with col detection
  3. Catalog matching per item
  4. Enrich with historical quote data (price context, anomaly detection)
  5. [Optional] LLM extraction override when ANTHROPIC_API_KEY is set
  6. Store DocumentExtraction
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
from app.services.ingestion.learner import (
    build_llm_examples,
    enrich_items_with_history,
    historical_price_context,
)
from app.services.ingestion.llm_extractor import extract_with_llm, merge_llm_with_heuristic
from app.services.ingestion.normalizer import normalize_unit
from app.services.ingestion.parsers.pdf import PdfParser
from app.services.ingestion.parsers.xlsx import XlsxParser
from app.services.matching.catalog_matcher import (
    MatchResult,
    best_supplier_offer,
    build_catalog_index,
    build_supplier_offer_index,
    match_item,
)

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


# Sumarni/rekapitulacijski redovi koje NE smijemo tretirati kao stavke
# (npr. "UKUPNO BEZ PDV-a", "Sveukupno", "Osnovica", "Za platiti"). Filtriramo
# samo ako red NEMA količinu — prava stavka uvijek ima količinu, pa nema lažnih pogodaka.
# Usidreno na POČETAK opisa (uz opcijski redni broj/interpunkciju "1. ", "- ")
# da se ne okine na summary-riječ usred pravog opisa ("Mjerenje ukupne
# instalacije"). Prefiks-stemovi hvataju deklinacije (ukupno/ukupna, osnovica).
# Filtrira se SAMO ako red nema količinu → prave stavke (imaju kol.) ostaju.
_SUMMARY_RE = re.compile(
    r"^[\s\d.,)\-]*(ukupn|sveukupn|zbroj|rekapitulacij|osnovic|za\s*platit|"
    r"total|bez\s*pdv|sa\s*pdv|pdv\b)",
    re.IGNORECASE,
)


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
        def get(col, row=row):  # row=row: bind po iteraciji
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

        # Preskoči sumarne redove (UKUPNO / PDV / zbroj) bez količine
        if qty is None and _SUMMARY_RE.search(desc):
            continue

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

    # Heuristic extraction
    heuristic_items: list[dict] = []
    for table in parsed.tables:
        heuristic_items.extend(_extract_items_from_table(table, source_method))

    log.info("heuristic_extraction_done", items=len(heuristic_items))

    # Katalog se vektorizira JEDNOM, pa svaka stavka matcha protiv tog indeksa
    catalog_index = await build_catalog_index(db, org_id)

    # Catalog matching for each heuristic item
    for item in heuristic_items:
        try:
            result: MatchResult = await match_item(
                db=db,
                org_id=org_id,
                description=item["description"],
                sku_hint=item.get("sku_hint"),
                index=catalog_index,
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

    # Fallback nabavne cijene iz cjenika dobavljača za stavke BEZ skladišnog matcha
    try:
        offer_index = await build_supplier_offer_index(db, org_id)
        if offer_index:
            for item in heuristic_items:
                if item.get("accepted_match"):
                    continue
                offer = best_supplier_offer(item["description"], item.get("sku_hint"), offer_index)
                if offer:
                    item["supplier_offer"] = offer
    except Exception as e:
        log.warning("supplier_offer_error", err=str(e))

    # Load historical price context for enrichment
    history = await historical_price_context(db=db, org_id=org_id)
    heuristic_items = enrich_items_with_history(heuristic_items, history)
    log.info("history_enrichment_done", history_records=len(history))

    # LLM extraction (override if API key available)
    final_items = heuristic_items
    llm_used = False

    if parsed.raw_text and len(parsed.raw_text) > 50:
        historical_examples = await build_llm_examples(db=db, org_id=org_id)
        llm_items = await extract_with_llm(parsed.raw_text, historical_examples)

        if llm_items:
            final_items = merge_llm_with_heuristic(llm_items, heuristic_items)
            llm_used = True
            log.info("llm_extraction_merged", llm_items=len(llm_items))

    # Overall confidence
    confidences = [i["confidence"] for i in final_items]
    overall = sum(confidences) / len(confidences) if confidences else 0.0
    doc_review = any(i.get("needs_review") for i in final_items) or overall < 0.85

    # Count anomalies for logging
    anomalies = sum(1 for i in final_items if i.get("price_anomaly"))
    if anomalies:
        log.warning("price_anomalies_detected", count=anomalies)

    extraction = DocumentExtraction(
        document_id=document.id,
        raw_text=parsed.raw_text[:30_000],
        structured_data={
            "line_items": final_items,
            "item_count": len(final_items),
            "source": source_method,
            "llm_used": llm_used,
            "price_anomalies": anomalies,
            "history_records_used": len(history),
        },
        extraction_method="llm" if llm_used else source_method,
        confidence=Decimal(str(round(overall, 2))),
        needs_review=doc_review,
    )
    db.add(extraction)
    document.status = "parsed"
    document.detected_lang = parsed.detected_lang
    await db.commit()
    await db.refresh(extraction)

    log.info("ingestion_complete",
             items=len(final_items),
             confidence=overall,
             llm_used=llm_used,
             anomalies=anomalies)
    return extraction
