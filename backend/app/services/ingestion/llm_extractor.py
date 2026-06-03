"""
LLM-based document extraction using Claude.

Activated when ANTHROPIC_API_KEY is set. Falls back gracefully to
heuristic pipeline when not available.

Uses historical quote examples (from learner.py) as few-shot context
so the model understands the organization's product vocabulary.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_SYSTEM = """\
Ti si stručnjak za ekstrakciju podataka iz nabavnih dokumenata (RFQ, troškovnici).

Zadatak: iz priloženog dokumenta (Excel/CSV tekst) izvuci sve stavke.

Pravila:
- Izvuci SAMO ono što postoji u dokumentu. Ne izmišljaj podatke.
- description: puni naziv/opis artikla iz dokumenta (kopiraj verbatim)
- quantity: broj (može biti decimalan). Ako nema, stavi null.
- unit: jedinica mjere normalizirana na: pcs, m, m2, m3, kg, set, lot, box, l
- unit_price: cijena po jedinici iz dokumenta. Ako nema, stavi null.
- sku: šifra artikla iz dokumenta ako postoji, inače null
- confidence: 0.95 za jasne tablice, 0.75 za nejasne

Vrati SAMO JSON array, bez ikakvih komentara:
[{"description":"...","quantity":N,"unit":"...","unit_price":N_or_null,"sku":"...or null","confidence":0.95}, ...]
"""


async def extract_with_llm(
    raw_text: str,
    historical_examples: str = "",
) -> list[dict] | None:
    """
    Call Claude to extract line items. Returns list or None if unavailable.
    """
    from app.config import settings

    if not settings.ANTHROPIC_API_KEY:
        return None

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

        user_msg = ""
        if historical_examples:
            user_msg += historical_examples + "\n\n"

        user_msg += f"Dokument za ekstrakciju:\n---\n{raw_text[:12_000]}\n---"

        resp = await client.messages.create(
            model=settings.ANTHROPIC_MODEL_DEFAULT,
            max_tokens=4096,
            temperature=0.0,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )

        text = resp.content[0].text.strip()

        # Extract JSON array from response
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if not match:
            logger.warning("llm_extractor_no_json_in_response")
            return None

        items = json.loads(match.group())
        logger.info("llm_extraction_done", items=len(items),
                    input_tokens=resp.usage.input_tokens,
                    output_tokens=resp.usage.output_tokens)
        return items

    except Exception as e:
        logger.error("llm_extraction_failed", error=str(e))
        return None


def merge_llm_with_heuristic(
    llm_items: list[dict],
    heuristic_items: list[dict],
) -> list[dict]:
    """
    Combine LLM + heuristic results.
    LLM wins on description and quantity.
    Heuristic wins on match_candidates (catalog matching).
    """
    if not heuristic_items:
        return [
            {
                "position": i + 1,
                "description": item.get("description", ""),
                "quantity": item.get("quantity"),
                "unit": item.get("unit", "pcs"),
                "unit_price": item.get("unit_price"),
                "sku_hint": item.get("sku"),
                "confidence": item.get("confidence", 0.85),
                "needs_review": item.get("confidence", 0.85) < 0.85,
                "match_candidates": [],
                "accepted_match": None,
            }
            for i, item in enumerate(llm_items)
        ]

    # Match LLM items to heuristic by position / description similarity
    from difflib import SequenceMatcher
    merged = []
    used_heuristic: set[int] = set()

    for i, llm_item in enumerate(llm_items):
        best_h = None
        best_sim = 0.0
        for j, h_item in enumerate(heuristic_items):
            if j in used_heuristic:
                continue
            sim = SequenceMatcher(
                None,
                llm_item.get("description", "").lower(),
                h_item.get("description", "").lower(),
            ).ratio()
            if sim > best_sim:
                best_sim = sim
                best_h = (j, h_item)

        base = best_h[1] if best_h and best_sim > 0.5 else {}
        if best_h:
            used_heuristic.add(best_h[0])

        merged.append({
            "position": i + 1,
            "description": llm_item.get("description") or base.get("description", ""),
            "quantity": llm_item.get("quantity") or base.get("quantity"),
            "unit": llm_item.get("unit") or base.get("unit", "pcs"),
            "unit_price": llm_item.get("unit_price") or base.get("unit_price"),
            "sku_hint": llm_item.get("sku") or base.get("sku_hint"),
            "confidence": max(
                llm_item.get("confidence", 0.8),
                base.get("confidence", 0.0),
            ),
            "needs_review": llm_item.get("confidence", 0.8) < 0.85,
            "match_candidates": base.get("match_candidates", []),
            "accepted_match": base.get("accepted_match"),
            "historical_price": base.get("historical_price"),
            "historical_cost": base.get("historical_cost"),
            "price_anomaly": base.get("price_anomaly", False),
        })

    return merged
