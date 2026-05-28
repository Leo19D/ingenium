"""Normalize units, currencies, numbers across documents."""

from __future__ import annotations

UNIT_ALIASES = {
    # pieces
    "pcs": "pcs", "pc": "pcs", "kom": "pcs", "kpl": "pcs",
    "stk": "pcs", "stück": "pcs", "штук": "pcs", "шт": "pcs",
    "unit": "pcs", "unidad": "pcs", "pieza": "pcs", "u": "pcs",
    # length
    "m": "m", "meter": "m", "metar": "m", "metre": "m", "mtr": "m",
    # area
    "m2": "m2", "m²": "m2", "sqm": "m2",
    # volume
    "m3": "m3", "m³": "m3", "cbm": "m3",
    # mass
    "kg": "kg", "kilogram": "kg",
    "g": "g", "gram": "g",
    # liquid
    "l": "l", "liter": "l", "litar": "l",
    "ml": "ml",
    # packaging
    "set": "set", "kit": "set", "komplet": "set",
    "box": "box", "kutija": "box", "carton": "box",
    "lot": "lot", "lt": "lot",
}


def normalize_unit(unit: str | None) -> str:
    if not unit:
        return "pcs"
    key = unit.strip().lower().rstrip(".")
    return UNIT_ALIASES.get(key, key)


CURRENCY_SYMBOLS = {
    "€": "EUR", "$": "USD", "£": "GBP", "¥": "JPY",
    "kn": "HRK", "kč": "CZK", "zł": "PLN", "fr": "CHF",
    "₽": "RUB", "₺": "TRY", "₹": "INR", "₩": "KRW",
}


def normalize_currency(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    if len(s) == 3 and s.isalpha():
        return s.upper()
    return CURRENCY_SYMBOLS.get(s.lower())
