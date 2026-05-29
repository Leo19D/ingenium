"""
Catalog matcher — finds best stock item match for an extracted line item.

Stages (all in-process, no pgvector needed for dev/SQLite):
  1. Exact SKU match
  2. Fuzzy name match (difflib SequenceMatcher)
  3. Word-overlap score (tokenized intersection)
  4. LLM ranker — only if ANTHROPIC_API_KEY is set AND top candidates are ambiguous
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.stock import StockItem


@dataclass
class MatchCandidate:
    stock_item_id: UUID
    sku: str
    name: str
    category: str | None
    unit: str
    unit_cost: Decimal | None
    quantity_on_hand: Decimal
    score: float          # 0..1
    match_method: str     # exact_sku | fuzzy_name | word_overlap
    explanation: str


@dataclass
class MatchResult:
    description: str
    sku_hint: str | None
    candidates: list[MatchCandidate] = field(default_factory=list)
    accepted: MatchCandidate | None = None   # auto-accepted if score >= 0.92
    needs_review: bool = True


def _tokenize(text: str) -> set[str]:
    """Lowercase words, remove noise."""
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))


def _fuzzy(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _word_overlap(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


async def match_item(
    *,
    db: AsyncSession,
    org_id: UUID,
    description: str,
    sku_hint: str | None = None,
    top_n: int = 3,
) -> MatchResult:
    result = MatchResult(description=description, sku_hint=sku_hint)

    items_q = await db.execute(
        select(StockItem).where(StockItem.org_id == org_id)
    )
    stock: list[StockItem] = list(items_q.scalars().all())
    if not stock:
        return result

    scored: list[tuple[float, str, StockItem]] = []

    for item in stock:
        # Stage 1: exact SKU
        if sku_hint and sku_hint.strip().lower() == item.sku.lower():
            scored.append((1.0, "exact_sku", item))
            continue

        # Stage 2: fuzzy name
        fscore = _fuzzy(description, item.name)

        # Stage 3: word overlap (boost)
        wscore = _word_overlap(description, item.name)

        # Also check SKU overlap if sku_hint given
        sku_boost = 0.0
        if sku_hint:
            sku_boost = _fuzzy(sku_hint, item.sku) * 0.3

        combined = fscore * 0.5 + wscore * 0.4 + sku_boost + 0.1
        combined = min(combined, 0.99)  # reserve 1.0 for exact SKU

        method = "fuzzy_name" if fscore >= wscore else "word_overlap"
        scored.append((combined, method, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_n]

    for score, method, item in top:
        if score < 0.25:
            continue
        result.candidates.append(MatchCandidate(
            stock_item_id=item.id,
            sku=item.sku,
            name=item.name,
            category=item.category,
            unit=item.unit,
            unit_cost=item.unit_cost,
            quantity_on_hand=item.quantity_on_hand,
            score=round(score, 3),
            match_method=method,
            explanation=f"Sličnost naziva {score:.0%}",
        ))

    if result.candidates and result.candidates[0].score >= 0.92:
        result.accepted = result.candidates[0]
        result.needs_review = False

    return result
