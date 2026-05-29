"""XLSX/XLS parser — heuristic column detection + openpyxl."""

from __future__ import annotations

import io
import re
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

from app.services.ingestion.parsers.base import DocumentParser, ParsedDocument, ParsedTable

_DESC_KW  = {"opis", "naziv", "description", "bezeichnung", "article", "artikl",
              "artikal", "item", "roba", "produkt", "stavka", "position", "pos"}
_QTY_KW   = {"kol", "količina", "qty", "menge", "cantidad", "komada", "kolicina",
              "kol.", "quantity", "amount", "kom"}
_UNIT_KW  = {"jed", "jedinica", "unit", "einheit", "mjera", "mjere", "um", "u/m", "jm"}
_PRICE_KW = {"cijena", "cena", "price", "preis", "vp", "vpcj", "jedinična",
              "j.c.", "eur/jed", "nabavna", "prodajna", "tarifa", "jed.cij"}
_SKU_KW   = {"sku", "šifra", "sifra", "code", "art", "artikelnr", "šif", "katbr"}


def _kw_score(header: str, keywords: set[str]) -> int:
    h = header.lower().strip()
    return sum(1 for kw in keywords if kw in h)


def _detect_columns(headers: list[str]) -> dict[str, int | None]:
    scored: dict[str, list[tuple[int, int]]] = {
        k: [] for k in ("description", "quantity", "unit", "unit_price", "sku")
    }
    mapping = {
        "description": _DESC_KW, "quantity": _QTY_KW, "unit": _UNIT_KW,
        "unit_price": _PRICE_KW, "sku": _SKU_KW,
    }
    for idx, h in enumerate(headers):
        for field, kws in mapping.items():
            score = _kw_score(h, kws)
            if score:
                scored[field].append((score, idx))

    result: dict[str, int | None] = {}
    used: set[int] = set()
    for field in ("description", "quantity", "unit", "unit_price", "sku"):
        chosen = None
        for _, idx in sorted(scored[field], reverse=True):
            if idx not in used:
                chosen = idx
                used.add(idx)
                break
        result[field] = chosen

    if result["description"] is None:
        result["description"] = 0 if headers else None
    return result


def _find_header_row(ws, max_scan: int = 20) -> int:
    for row_idx in range(1, min(max_scan, ws.max_row or 1) + 1):
        cells = [ws.cell(row_idx, c).value for c in range(1, min((ws.max_column or 1) + 1, 20))]
        non_empty = [c for c in cells if c is not None and str(c).strip()]
        text_cells = [c for c in non_empty if isinstance(c, str)]
        if len(non_empty) >= 3 and len(text_cells) >= 2:
            return row_idx
    return 1


class XlsxParser(DocumentParser):
    async def parse(self, file_bytes: bytes, filename: str) -> ParsedDocument:
        wb = load_workbook(filename=io.BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.active

        header_row_idx = _find_header_row(ws)
        max_col = ws.max_column or 1
        raw_headers = [
            str(ws.cell(header_row_idx, c).value or "").strip()
            for c in range(1, max_col + 1)
        ]
        col_map = _detect_columns(raw_headers)

        rows: list[list[str]] = []
        for row_idx in range(header_row_idx + 1, (ws.max_row or 1) + 1):
            cells = [ws.cell(row_idx, c).value for c in range(1, max_col + 1)]
            if not any(c is not None and str(c).strip() for c in cells):
                continue
            rows.append([str(c) if c is not None else "" for c in cells])

        table = ParsedTable(rows=rows, page=None, bbox=None)
        # Attach metadata as extra attrs
        object.__setattr__(table, "col_map", col_map)
        object.__setattr__(table, "headers", raw_headers)

        wb.close()
        return ParsedDocument(
            raw_text="\n".join("\t".join(r) for r in rows),
            tables=[table],
            detected_lang="hr",
            metadata={"header_row": header_row_idx, "col_map": col_map, "headers": raw_headers},
        )
