"""PDF parser — 3 razine:
  1. pdfplumber extract_tables (digitalni PDF s tablicom)
  2. tekstualni retci (digitalni PDF bez okvira tablice)
  3. OCR (tesseract) za skenirane PDF-ove (slike)

Sve razine proizvode ParsedTable s col_map (kao XLSX) → ista heuristika dalje.
"""

from __future__ import annotations

import io
import logging
import re

from app.services.ingestion.parsers.base import DocumentParser, ParsedDocument, ParsedTable
from app.services.ingestion.parsers.xlsx import _detect_columns

logger = logging.getLogger(__name__)

# Jedinice mjere u troškovnicima (HR) — usidrenje za parsiranje retka
_UNITS = {
    "kom", "komada", "kpl", "kompleta", "m", "m1", "m2", "m²", "m3", "m³",
    "kg", "l", "lit", "t", "h", "sat", "sati", "par", "para", "set", "pak",
    "rola", "kut", "kdn", "paus", "ks",
}


def _is_num(tok: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:[.,]\d+)?", tok))


# OCR zna spojiti broj i jedinicu ("25kom", "500m") — razdvoji ih
_GLUED = re.compile(
    r"(\d)(" + "|".join(sorted(_UNITS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _split_glued(line: str) -> str:
    return _GLUED.sub(r"\1 \2", line)


def _parse_line(line: str) -> list[str] | None:
    """Razbij redak troškovnika u [opis, količina, jed., cijena].

    Usidri se na JEDINICU (kom/m/kpl...) — količina je broj prije nje, cijena
    zadnji broj iza. Opis ostaje cijel (uklj. brojeve u nazivu: 60x60, 40W).
    Fallback bez jedinice: zadnji broj = cijena, pretposljednji = količina.
    """
    line = _split_glued(line.strip())
    tokens = line.split()
    if len(tokens) < 2:
        return None

    unit_idx = next(
        (i for i, t in enumerate(tokens) if t.lower().strip(".,:") in _UNITS), None
    )

    if unit_idx is not None and unit_idx >= 1 and _is_num(tokens[unit_idx - 1]):
        qi = unit_idx - 1
        qty = tokens[qi]
        unit = tokens[unit_idx].strip(".,:")
        desc = " ".join(tokens[:qi]).strip(" .:-\t")
        after = [t for t in tokens[unit_idx + 1:] if _is_num(t)]
        price = after[-1] if after else ""
    else:
        # Bez jasne jedinice: zadnji broj = cijena, pretposljednji = količina
        num_idx = [i for i, t in enumerate(tokens) if _is_num(t)]
        if not num_idx:
            return None
        pi = num_idx[-1]
        price = tokens[pi]
        if len(num_idx) >= 2:
            qi = num_idx[-2]
            qty = tokens[qi]
            desc = " ".join(tokens[:qi]).strip(" .:-\t")
        else:
            qty = ""
            desc = " ".join(tokens[:pi]).strip(" .:-\t")
        unit = ""

    if len(desc) < 3:
        return None
    return [desc, qty, unit, price]


def _rows_from_text(text: str) -> list[list[str]]:
    """Parsiraj redove iz čistog teksta (digitalni PDF bez okvira ili OCR izlaz)."""
    rows: list[list[str]] = []
    for raw in text.splitlines():
        parsed = _parse_line(raw)
        if parsed:
            rows.append(parsed)
    return rows


def _make_table(rows: list[list[str]], page: int | None,
                col_map: dict | None = None) -> ParsedTable:
    table = ParsedTable(rows=rows, page=page)
    object.__setattr__(table, "col_map", col_map or {
        "description": 0, "quantity": 1, "unit": 2, "unit_price": 3,
    })
    return table


def _ocr_pages(file_bytes: bytes) -> str:
    """Skenirani PDF → render stranica (pymupdf) → OCR (tesseract binary preko
    subprocessa; pytesseract wrapper je nepouzdan). Vrati prepoznati tekst."""
    import os
    import shutil
    import subprocess
    import tempfile

    try:
        import fitz  # pymupdf
    except ImportError as e:
        logger.warning("ocr_render_dep_missing: %s", e)
        return ""
    if not shutil.which("tesseract"):
        logger.warning("tesseract_binary_missing")
        return ""

    out: list[str] = []
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(pix.tobytes("png"))
                path = f.name
            try:
                r = subprocess.run(
                    ["tesseract", path, "stdout", "-l", "hrv+eng"],
                    capture_output=True, timeout=120, check=False,
                )
                out.append(r.stdout.decode("utf-8", "replace"))
            finally:
                os.unlink(path)
    except Exception as e:
        logger.exception("ocr_failed: %s", e)
        return ""
    return "\n".join(out)


class PdfParser(DocumentParser):
    async def parse(self, file_bytes: bytes, filename: str) -> ParsedDocument:
        try:
            import pdfplumber
        except ImportError:
            return ParsedDocument(raw_text="", tables=[], detected_lang=None,
                                  metadata={"error": "pdfplumber not installed"})

        raw_text_parts: list[str] = []
        tables: list[ParsedTable] = []
        method = "pdfplumber_table"

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                raw_text_parts.append(page.extract_text() or "")
                for tbl in page.extract_tables() or []:
                    if not tbl:
                        continue
                    rows = [
                        [str(c) if c is not None else "" for c in row]
                        for row in tbl
                        if any(c is not None and str(c).strip() for c in row)
                    ]
                    if len(rows) >= 2:
                        # 1. razina: tablica s okvirom → header + col_map (kao XLSX)
                        headers, data_rows = rows[0], rows[1:]
                        tables.append(_make_table(
                            data_rows, page_num, _detect_columns(headers, data_rows)))

        full_text = "\n".join(raw_text_parts).strip()

        # 2. razina: nema tablica ali ima teksta → parsiraj retke
        if not tables and len(full_text) > 20:
            rows = _rows_from_text(full_text)
            if rows:
                tables.append(_make_table(rows, 1))
                method = "pdf_text_lines"

        # 3. razina: skeniran (nema teksta) → OCR
        if not tables and len(full_text) <= 20:
            ocr_text = _ocr_pages(file_bytes)
            if ocr_text:
                raw_text_parts.append(ocr_text)
                rows = _rows_from_text(ocr_text)
                if rows:
                    tables.append(_make_table(rows, 1))
                    method = "ocr"

        return ParsedDocument(
            raw_text="\n\n".join(raw_text_parts),
            tables=tables,
            detected_lang=None,
            metadata={"extraction_method": method},
        )
