"""PDF izvještaja (fpdf2) — sažetak ponuda, ishoda i nabave za razdoblje."""

from __future__ import annotations

from fpdf import FPDF

from app.services.quote.pdf_generator import _hex_to_rgb, _txt

_DARK = (27, 41, 64)
_GREY = (88, 103, 128)
_DEFAULT = (26, 86, 153)


class _ReportPDF(FPDF):
    def __init__(self, org_name: str, accent: tuple):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.org_name = org_name
        self.accent = accent
        self.set_auto_page_break(auto=True, margin=20)

    def header(self) -> None:
        self.set_fill_color(*self.accent)
        self.rect(10, 10, 8, 8, "F")
        self.set_xy(20, 10)
        self.set_font("Helvetica", "B", 15)
        self.set_text_color(*_DARK)
        self.cell(0, 8, _txt(self.org_name), ln=True)
        self.set_draw_color(*self.accent)
        self.set_line_width(0.6)
        self.line(10, 22, 200, 22)
        self.ln(12)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*_GREY)
        self.cell(0, 5, _txt(f"{self.org_name} - Izvjestaj - Stranica {self.page_no()}"), align="C")


def _fmt(v: object) -> str:
    if isinstance(v, (int, float)):
        return f"{v:,.2f}" if isinstance(v, float) else str(v)
    return _txt(str(v))


def generate_report_pdf(*, report: dict, org_name: str = "Ingenium",
                        brand_color: str | None = None) -> bytes:
    accent = _hex_to_rgb(brand_color) if brand_color else _DEFAULT
    pdf = _ReportPDF(org_name, accent)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*_DARK)
    pdf.cell(0, 10, "POSLOVNI IZVJESTAJ", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_GREY)
    per = report["period"]
    pdf.cell(0, 6, _txt(f"Razdoblje: {per['from']} - {per['to']}"), ln=True)
    pdf.ln(6)

    def section(title: str, rows: list[tuple[str, object]]) -> None:
        pdf.set_fill_color(*accent)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, _txt(title), ln=True, fill=True)
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 10)
        for label, value in rows:
            pdf.set_text_color(*_GREY)
            pdf.cell(120, 7, _txt(label), border="B")
            pdf.set_text_color(*_DARK)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 7, _fmt(value), border="B", align="R", ln=True)
            pdf.set_font("Helvetica", "", 10)
        pdf.ln(6)

    q, o, p = report["quotes"], report["outcomes"], report["procurement"]
    section("PONUDE", [
        ("Kreirano", q["created"]),
        ("Vrijednost kreiranih (EUR)", float(q["created_value"])),
        ("Poslano u razdoblju", q["sent_in_period"]),
        *[(f"   status: {k}", v) for k, v in q["by_status"].items()],
    ])
    won_margin = o["avg_margin_won_pct"]
    section("ISHODI", [
        ("Dobiveno", o["won"]),
        ("Vrijednost dobivenih (EUR)", float(o["won_value"])),
        ("Izgubljeno", o["lost"]),
        ("Vrijednost izgubljenih (EUR)", float(o["lost_value"])),
        ("Win rate (%)", o["win_rate_pct"]),
        ("Prosj. marza dobivenih (%)", won_margin if won_margin is not None else "-"),
        *[(f"   razlog gubitka: {r}", c) for r, c in o["top_lost_reasons"]],
    ])
    section("NABAVA", [
        ("Narudzbenice kreirane", p["po_created"]),
        ("Zaprimljeno", p["po_received"]),
        ("Nabavna vrijednost zaprimljenog (EUR)", float(p["purchase_value"])),
    ])

    return bytes(pdf.output())
