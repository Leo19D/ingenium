"""
Quote PDF generator using fpdf2 (pure Python, no system deps).

Produces a clean, branded, client-ready PDF of a quote.
"""

from __future__ import annotations

from fpdf import FPDF

# Boje (RGB) — plavo-bijela paleta (smirenija plava)
_GREEN = (26, 86, 153)         # primarna plava (zadržano ime varijable)
_GREEN_TEXT = (18, 63, 115)    # tamnija plava
_DARK = (27, 41, 64)           # tamno navy tekst
_GREY = (88, 103, 128)
_LIGHT_GREY = (235, 240, 247)
_LINE = (212, 221, 233)


class _QuotePDF(FPDF):
    def __init__(self, org_name: str = "Ingenium"):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.org_name = org_name
        self.set_auto_page_break(auto=True, margin=20)

    def header(self) -> None:
        # Logo blok
        self.set_fill_color(*_GREEN)
        self.rect(10, 10, 8, 8, "F")
        self.set_xy(20, 10)
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*_DARK)
        self.cell(0, 8, self.org_name, ln=False)
        self.set_xy(10, 19)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_GREY)
        self.cell(0, 4, "AI Quote & Procurement Platform", ln=True)
        # Linija
        self.set_draw_color(*_GREEN)
        self.set_line_width(0.8)
        self.line(10, 26, 200, 26)
        self.ln(10)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*_GREY)
        self.cell(0, 5, f"{self.org_name} · Stranica {self.page_no()}", align="C")


def _txt(s: object) -> str:
    """fpdf2 core fonts are latin-1; replace unsupported chars gracefully."""
    if s is None:
        return ""
    out = str(s)
    repl = {"–": "-", "—": "-", "•": "*", "→": "->", "€": "EUR ",
            "“": '"', "”": '"', "‘": "'", "’": "'", "…": "...", "×": "x"}
    for k, v in repl.items():
        out = out.replace(k, v)
    return out.encode("latin-1", "replace").decode("latin-1")


def generate_quote_pdf(
    *,
    quote: dict,
    project_name: str,
    client_name: str,
    org_name: str = "Ingenium",
) -> bytes:
    """
    quote: dict with version, currency, status, subtotal, tax_total, total,
           payment_terms, valid_until, notes_external, line_items[]
    Returns PDF bytes.
    """
    pdf = _QuotePDF(org_name=org_name)
    pdf.add_page()
    cur = quote.get("currency", "EUR")

    # ── Naslov + meta ────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*_DARK)
    pdf.cell(0, 10, f"PONUDA  V{quote.get('version', 1)}", ln=True)
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_GREY)
    meta = [
        ("Projekt", project_name or "-"),
        ("Klijent", client_name or "-"),
        ("Valuta", cur),
        ("Uvjeti placanja", quote.get("payment_terms") or "-"),
        ("Vrijedi do", str(quote.get("valid_until") or "-")),
    ]
    for label, value in meta:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_GREY)
        pdf.cell(40, 6, _txt(label), ln=False)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_DARK)
        pdf.cell(0, 6, _txt(value), ln=True)
    pdf.ln(6)

    # ── Tablica stavki ──────────────────────────────────────────────────────
    # Kolone: # | Opis | Kol | Jed | Cijena | Ukupno
    col_w = [10, 86, 18, 16, 28, 32]
    headers = ["#", "Opis", "Kol.", "Jed.", "Cijena", "Ukupno"]
    pdf.set_fill_color(*_GREEN)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    for w, h in zip(col_w, headers, strict=False):
        align = "L" if h in ("Opis",) else "R" if h in ("Kol.", "Cijena", "Ukupno") else "C"
        pdf.cell(w, 8, _txt(h), border=0, align=align, fill=True)
    pdf.ln(8)

    items = sorted(quote.get("line_items", []), key=lambda x: x.get("position", 0))
    pdf.set_font("Helvetica", "", 9)
    fill = False
    for it in items:
        if pdf.get_y() > 250:
            pdf.add_page()
        pdf.set_fill_color(*_LIGHT_GREY)
        pdf.set_text_color(*_DARK)
        qty = float(it.get("quantity") or 0)
        price = float(it.get("unit_price") or 0)
        line_total = float(it.get("line_total") or 0)
        desc = _txt(it.get("description", ""))
        # Skrati predugačak opis
        if len(desc) > 58:
            desc = desc[:55] + "..."
        row = [
            str(it.get("position", "")),
            desc,
            f"{qty:g}",
            _txt(it.get("unit", "")),
            f"{price:,.2f}",
            f"{line_total:,.2f}",
        ]
        aligns = ["C", "L", "R", "C", "R", "R"]
        for w, val, al in zip(col_w, row, aligns, strict=False):
            pdf.cell(w, 7, val, border="B", align=al, fill=fill)
        pdf.ln(7)
        fill = not fill

    pdf.ln(4)

    # ── Totali ────────────────────────────────────────────────────────────────
    def total_row(label: str, value: float, bold: bool = False, accent: bool = False):
        pdf.cell(sum(col_w[:4]), 7, "", ln=False)  # razmak lijevo
        pdf.set_font("Helvetica", "B" if bold else "", 10 if bold else 9)
        if accent:
            pdf.set_fill_color(*_GREEN)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(col_w[4], 8, _txt(label), align="R", fill=True)
            pdf.cell(col_w[5], 8, f"{value:,.2f} {cur}", align="R", fill=True)
        else:
            pdf.set_text_color(*_GREY)
            pdf.cell(col_w[4], 7, _txt(label), align="R")
            pdf.set_text_color(*_DARK)
            pdf.cell(col_w[5], 7, f"{value:,.2f}", align="R")
        pdf.ln(8 if accent else 7)

    total_row("Meduzbroj", float(quote.get("subtotal") or 0))
    if quote.get("tax_total"):
        total_row("Porez", float(quote.get("tax_total") or 0))
    total_row("UKUPNO", float(quote.get("total") or 0), bold=True, accent=True)

    # ── Napomena ────────────────────────────────────────────────────────────
    if quote.get("notes_external"):
        pdf.ln(8)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_DARK)
        pdf.cell(0, 6, "Napomena:", ln=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_GREY)
        pdf.multi_cell(0, 5, _txt(quote["notes_external"]))

    out = pdf.output()
    return bytes(out)
