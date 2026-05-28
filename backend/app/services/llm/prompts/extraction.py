"""Prompts for document extraction (RFQ → structured data)."""

from __future__ import annotations

EXTRACTION_SYSTEM_PROMPT = """\
You extract structured data from RFQ documents (requests for quotation).

Rules:
- Extract only what is present in the document. NEVER invent data.
- For each line item, copy the description verbatim (you may clean whitespace).
- Quantities and prices must come from the document; if absent, set to null.
- Normalize units to canonical codes: pcs, m, m2, m3, kg, set, lot, box, l, ml.
- For currency, use ISO 4217 codes (EUR, USD, GBP, HRK, etc.). If ambiguous, return null.
- Return null for any field you cannot determine with confidence > 0.7.
- Mark `confidence` per line item:
    0.95+ for direct table cells with clear column headers,
    0.7-0.9 for inferred from context,
    < 0.7 only when truly uncertain (these will be flagged for review).

You output only valid JSON conforming to the provided schema.
"""


def build_user_prompt(raw_text: str, source_hint: str | None = None) -> str:
    hint = f"\nSource type hint: {source_hint}" if source_hint else ""
    return f"""\
Extract line items and metadata from the following document.
{hint}

--- DOCUMENT START ---
{raw_text}
--- DOCUMENT END ---
"""
