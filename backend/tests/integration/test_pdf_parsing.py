"""Integration: PDF troškovnik parsing — pdfplumber tablica → stavke s col_map.

Regresija za bug gdje PDF parser nije postavljao col_map (kao XLSX) → heuristika
nije znala koji stupac je opis/količina/cijena → 0 ekstrahiranih stavki.
"""

from __future__ import annotations

import pytest
from fpdf import FPDF

from app.services.ingestion.parsers.pdf import PdfParser
from app.services.ingestion.pipeline import _extract_items_from_table


def _make_pdf() -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 10)
    cols = [("Opis", 90), ("Kolicina", 30), ("Jed.", 20), ("Cijena", 30)]
    for n, w in cols:
        pdf.cell(w, 8, n, border=1)
    pdf.ln()
    pdf.set_font("Helvetica", size=10)
    rows = [
        ("LED panel 60x60 40W 4000K", "25", "kom", "32.50"),
        ("LED reflektor 50W IP65", "10", "kom", "45.00"),
        ("Kabel NYM-J 3x1.5mm2", "500", "m", "1.20"),
    ]
    for r in rows:
        for (_n, w), v in zip(cols, r, strict=False):
            pdf.cell(w, 8, v, border=1)
        pdf.ln()
    return bytes(pdf.output())


@pytest.mark.asyncio
async def test_pdf_table_extracts_items_with_colmap():
    parsed = await PdfParser().parse(_make_pdf(), "troskovnik.pdf")
    assert len(parsed.tables) == 1
    table = parsed.tables[0]
    col_map = getattr(table, "col_map", None)
    assert col_map is not None, "PDF tablica mora imati col_map (kao XLSX)"
    assert col_map.get("description") is not None
    assert col_map.get("quantity") is not None

    items = _extract_items_from_table(table, "pdfplumber")
    assert len(items) == 3, f"očekivano 3 stavke, dobiveno {len(items)}"
    descs = [i["description"] for i in items]
    assert any("LED panel" in d for d in descs)
    assert items[0]["quantity"] == 25.0
    assert items[0]["unit_price"] == 32.5


def _make_text_pdf() -> bytes:
    """PDF s tekstom ali BEZ okvira tablice (razina 2)."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 8, "TROSKOVNIK rasvjeta", new_x="LMARGIN", new_y="NEXT")
    for line in [
        "LED panel 60x60 40W 4000K   25 kom   32.50",
        "Kabel NYM-J 3x1.5mm2   500 m   1.20",
    ]:
        pdf.cell(0, 7, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


@pytest.mark.asyncio
async def test_pdf_text_lines_keeps_description_with_numbers():
    """Razina 2: opis s brojevima (60x60, 40W) ostaje cijel; qty/cijena iz kraja."""
    parsed = await PdfParser().parse(_make_text_pdf(), "troskovnik.pdf")
    assert parsed.metadata.get("extraction_method") == "pdf_text_lines"
    items = []
    for t in parsed.tables:
        items += _extract_items_from_table(t, "pdf")
    assert len(items) == 2
    led = next(i for i in items if "LED panel" in i["description"])
    assert led["description"] == "LED panel 60x60 40W 4000K"  # cijel opis
    assert led["quantity"] == 25.0
    assert led["unit_price"] == 32.5


def test_borderless_line_takes_unit_price_not_total():
    """Red 'kol jed jed.cijena ukupno' — uzmi JEDINIČNU (prvi broj iza jed.),
    ne ukupnu (zadnji). Bug: '40kom 22,00 880,00' davao je 880 umjesto 22."""
    from app.services.ingestion.parsers.pdf import _parse_line

    _desc, qty, unit, price = _parse_line(
        "2. Reflektor LED 50W IP65 crni  40kom  22,00  880,00"
    )
    assert qty == "40"
    assert unit == "kom"
    assert price == "22,00"  # jedinična, NE 880,00 (ukupno)

    # i kad nema ukupnog stupca — cijena ostaje ispravna
    _d, q2, _u, p2 = _parse_line("Spot GU10 7W  250kom  4,20")
    assert q2 == "250"
    assert p2 == "4,20"
