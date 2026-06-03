"""
Learning from historical quotes.

Provides:
  - historical_price_context() — average price per item name from past won quotes
  - enrich_items_with_history() — adds historical_price and price_anomaly to each item
  - build_llm_examples() — few-shot examples for LLM prompt from past quote lines
"""

from __future__ import annotations

from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.quote import Quote, QuoteLineItem, QuoteOutcome


async def historical_price_context(
    *,
    db: AsyncSession,
    org_id: UUID,
    limit: int = 200,
) -> list[dict]:
    """
    Load recent confirmed (won) quote line items as price reference.
    Returns list of {description, unit_price, unit_cost, unit}.
    """
    result = await db.execute(
        select(QuoteLineItem.description, QuoteLineItem.unit_price,
               QuoteLineItem.unit_cost, QuoteLineItem.unit)
        .join(Quote, Quote.id == QuoteLineItem.quote_id)
        .join(QuoteOutcome, QuoteOutcome.quote_id == Quote.id)
        .where(Quote.org_id == org_id, QuoteOutcome.outcome == "won")
        .order_by(Quote.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "description": row.description,
            "unit_price":  float(row.unit_price) if row.unit_price else None,
            "unit_cost":   float(row.unit_cost) if row.unit_cost else None,
            "unit":        row.unit,
        }
        for row in result.all()
    ]


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def enrich_items_with_history(
    items: list[dict],
    history: list[dict],
) -> list[dict]:
    """
    For each extracted item, find historically similar line items.
    Adds:
      - historical_price: average price from past won quotes
      - historical_cost:  average cost from past won quotes
      - price_anomaly: True if extracted price deviates >40% from historical
      - history_matches: top 2 similar historical items
    """
    if not history:
        return items

    enriched = []
    for item in items:
        desc = item.get("description", "")
        matches = []
        for hist in history:
            sim = _similarity(desc, hist["description"])
            if sim >= 0.5:
                matches.append((sim, hist))

        matches.sort(key=lambda x: x[0], reverse=True)
        top = matches[:3]

        hist_prices = [h["unit_price"] for _, h in top if h["unit_price"]]
        hist_costs  = [h["unit_cost"]  for _, h in top if h["unit_cost"]]

        avg_price = sum(hist_prices) / len(hist_prices) if hist_prices else None
        avg_cost  = sum(hist_costs)  / len(hist_costs)  if hist_costs  else None

        # Detect price anomaly: extracted RFQ price very different from our historical price
        anomaly = False
        if avg_price and item.get("unit_price"):
            ratio = item["unit_price"] / avg_price
            anomaly = ratio < 0.5 or ratio > 2.0

        enriched.append({
            **item,
            "historical_price": round(avg_price, 4) if avg_price else None,
            "historical_cost":  round(avg_cost, 4) if avg_cost else None,
            "price_anomaly": anomaly,
            "history_matches": [
                {
                    "description": h["description"],
                    "unit_price":  h["unit_price"],
                    "similarity":  round(sim, 2),
                }
                for sim, h in top[:2]
            ],
        })
    return enriched


async def build_llm_examples(
    *,
    db: AsyncSession,
    org_id: UUID,
    limit: int = 8,
) -> str:
    """
    Build a few-shot example block for the LLM extraction prompt,
    drawn from the last N confirmed (won) quote line items.
    """
    history = await historical_price_context(db=db, org_id=org_id, limit=limit * 5)
    if not history:
        return ""

    seen: set[str] = set()
    examples = []
    for h in history:
        key = h["description"][:40].lower()
        if key in seen:
            continue
        seen.add(key)
        examples.append(h)
        if len(examples) >= limit:
            break

    if not examples:
        return ""

    lines = ["Primjeri stavki iz prošlih uspješnih ponuda (za referencu):"]
    for ex in examples:
        price_str = f"  naša cijena: {ex['unit_price']}" if ex["unit_price"] else ""
        lines.append(f"  - {ex['description']} ({ex['unit']}){price_str}")

    return "\n".join(lines)
