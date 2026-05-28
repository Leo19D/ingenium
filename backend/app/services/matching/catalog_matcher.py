"""
Catalog matcher — finds the canonical product for an extracted line item.

Four-stage pipeline:
    1. Exact SKU match
    2. Fuzzy + Full-text search (pg_trgm + tsvector)
    3. Semantic embedding match (pgvector)
    4. LLM ranker (only if 1-3 ambiguous)

Returns ranked candidates with confidence. Caller decides whether to
auto-accept or route to human review.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class MatchCandidate:
    product_id: str
    sku: str
    name: str
    score: Decimal  # 0..1
    match_method: str  # 'exact', 'fuzzy', 'fts', 'embedding', 'llm'
    explanation: str


@dataclass
class MatchResult:
    line_item_description: str
    candidates: list[MatchCandidate]
    accepted: MatchCandidate | None  # None → needs human review
    needs_review: bool


class CatalogMatcher:
    async def match(
        self,
        *,
        org_id: str,
        description: str,
        specs: dict | None = None,
        sku_hint: str | None = None,
    ) -> MatchResult:
        """TODO: implement multi-stage matching."""
        # 1. SKU lookup
        # 2. FTS + pg_trgm via SQL
        # 3. Embedding cosine via pgvector
        # 4. If multiple candidates with score > 0.7 and no clear winner → LLM ranker
        # 5. Specs validator: reject candidate if specs contradict
        raise NotImplementedError("CatalogMatcher.match not yet implemented")
