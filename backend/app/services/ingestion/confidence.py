"""Confidence scoring for extracted line items."""

from __future__ import annotations

from decimal import Decimal


def score_line_item(
    *,
    has_quantity: bool,
    has_unit_price: bool,
    has_description: bool,
    source_method: str,
    sum_check_ok: bool,
) -> Decimal:
    """
    Naive but transparent confidence model. Replace with calibrated one
    when we have labeled data.
    """
    base = {
        "pdfplumber": Decimal("0.92"),
        "openpyxl": Decimal("0.95"),
        "azure_di": Decimal("0.85"),
        "textract": Decimal("0.83"),
        "llm": Decimal("0.75"),
        "manual": Decimal("1.00"),
    }.get(source_method, Decimal("0.6"))

    if not has_description:
        base -= Decimal("0.3")
    if not has_quantity:
        base -= Decimal("0.2")
    if not has_unit_price:
        base -= Decimal("0.1")
    if not sum_check_ok:
        base -= Decimal("0.15")

    return max(Decimal("0"), min(Decimal("1"), base))


def needs_review(confidence: Decimal, threshold: Decimal = Decimal("0.85")) -> bool:
    return confidence < threshold
