"""Unit: čišćenje ekstrakcije troškovnika — detekcija opisne kolone + sumarni redovi.

Pokriva dva stvarna nalaza iz probnog prolaza s neurednim dokumentima:
  1. "Stavka" (redni broj) ne smije progutati "Opis" za description kolonu.
  2. Sumarni redovi (UKUPNO / Osnovica / PDV / SVEUKUPNO) bez količine ne ulaze
     kao stavke, ali pravi proizvodi (imaju količinu) ostaju.
"""

from __future__ import annotations

import asyncio
import io

from openpyxl import Workbook

from app.services.ingestion.parsers.xlsx import XlsxParser
from app.services.ingestion.pipeline import _extract_items_from_table


def _parse_first_table(rows: list[list]):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    parsed = asyncio.run(XlsxParser().parse(buf.getvalue(), "t.xlsx"))
    return parsed.tables[0]


def test_stavka_does_not_steal_description_from_opis():
    table = _parse_first_table(
        [
            ["Stavka", "Opis", "JM", "Kol", "Cijena"],
            [1, "Reflektor LED 50W IP65 crni", "kom", 40, "22,00"],
            [2, "Spot ugradni GU10 7W", "kom", 250, "4,20"],
        ]
    )
    assert table.col_map["description"] == 1  # "Opis", ne "Stavka" (col 0)
    items = _extract_items_from_table(table, "openpyxl")
    descs = [i["description"] for i in items]
    assert "Reflektor LED 50W IP65 crni" in descs
    assert "Spot ugradni GU10 7W" in descs


def test_summary_rows_excluded_real_items_kept():
    table = _parse_first_table(
        [
            ["Stavka", "Opis", "JM", "Kol", "Cijena"],
            [1, "Reflektor LED 50W IP65 crni", "kom", 40, "22,00"],
            [2, "Spot ugradni GU10 7W", "kom", 250, "4,20"],
            ["", "Osnovica", "", "", "5.130,00"],
            ["", "PDV 25%", "", "", "1.282,50"],
            ["", "SVEUKUPNO sa PDV-om", "", "", "6.412,50"],
        ]
    )
    items = _extract_items_from_table(table, "openpyxl")
    assert len(items) == 2  # samo prave stavke
    descs = " ".join(i["description"].lower() for i in items)
    assert "osnovica" not in descs and "pdv" not in descs and "sveukupno" not in descs


def test_product_with_quantity_never_filtered():
    """Proizvod ostaje čak i da opis sliči sumarnom — jer ima količinu."""
    table = _parse_first_table(
        [
            ["R.br.", "Opis", "JM", "Kol", "Cijena"],
            [1, "Razdjelnik 12 modula", "kom", 5, "45,00"],
        ]
    )
    items = _extract_items_from_table(table, "openpyxl")
    assert len(items) == 1
    assert items[0]["description"] == "Razdjelnik 12 modula"


def test_summary_regex_anchored_no_midtext_false_positive():
    """Summary filter je usidren na početak opisa — riječ 'ukupne'/'PDV' usred
    pravog opisa NE smije izbaciti stavku (čak ni bez prepoznate količine)."""
    from app.services.ingestion.pipeline import _SUMMARY_RE

    assert not _SUMMARY_RE.search("Mjerenje i ispitivanje ukupne instalacije")
    assert not _SUMMARY_RE.search("Razdjelnik s PDV zaštitom IP44")
    assert _SUMMARY_RE.search("UKUPNO BEZ PDV-a")
    assert _SUMMARY_RE.search("Osnovica")
    assert _SUMMARY_RE.search("1. SVEUKUPNO sa PDV-om")
