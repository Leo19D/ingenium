"""PDF parser using pdfplumber for text-based PDFs."""

from __future__ import annotations

import io

from app.services.ingestion.parsers.base import DocumentParser, ParsedDocument, ParsedTable
from app.services.ingestion.parsers.xlsx import _detect_columns


class PdfParser(DocumentParser):
    async def parse(self, file_bytes: bytes, filename: str) -> ParsedDocument:
        try:
            import pdfplumber
        except ImportError:
            return ParsedDocument(raw_text="", tables=[], detected_lang=None,
                                  metadata={"error": "pdfplumber not installed"})

        raw_text_parts: list[str] = []
        tables: list[ParsedTable] = []

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                raw_text_parts.append(text)

                for tbl in page.extract_tables() or []:
                    if not tbl:
                        continue
                    rows = [
                        [str(cell) if cell is not None else "" for cell in row]
                        for row in tbl
                        if any(cell is not None and str(cell).strip() for cell in row)
                    ]
                    if len(rows) >= 2:
                        # Prvi red = header, ostali = podaci. Ista detekcija stupaca
                        # kao XLSX (keywords + number distribution) → col_map, da
                        # heuristika zna koji stupac je opis/količina/cijena.
                        headers = rows[0]
                        data_rows = rows[1:]
                        col_map = _detect_columns(headers, data_rows)
                        table = ParsedTable(rows=data_rows, page=page_num)
                        object.__setattr__(table, "col_map", col_map)
                        object.__setattr__(table, "headers", headers)
                        tables.append(table)

        return ParsedDocument(
            raw_text="\n\n".join(raw_text_parts),
            tables=tables,
            detected_lang=None,
            metadata={"pages": len(pdf.pages) if 'pdf' in dir() else 0},
        )
