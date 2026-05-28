"""
Pricing rule resolver — picks the right margin for a line item.

Priority (first match wins):
  1. Manual line override
  2. Client-specific price list
  3. Volume tier
  4. Category margin
  5. Default org margin
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class RuleContext:
    org_id: str
    client_id: str | None
    product_category: str | None
    quantity: Decimal
    landed_cost: Decimal


@dataclass
class ResolvedMargin:
    margin_pct: Decimal
    rule_name: str
    explanation: str


def resolve_margin(ctx: RuleContext) -> ResolvedMargin:
    """
    TODO: load actual rules from DB. This stub returns a sensible default
    so the engine works end-to-end during development.
    """
    # Example category defaults
    category_defaults = {
        "led_panel": Decimal("0.18"),
        "spotlight": Decimal("0.22"),
        "cable": Decimal("0.08"),
        "breaker": Decimal("0.12"),
        "installation": Decimal("0.35"),
    }
    if ctx.product_category and ctx.product_category in category_defaults:
        m = category_defaults[ctx.product_category]
        return ResolvedMargin(
            margin_pct=m,
            rule_name=f"category:{ctx.product_category}",
            explanation=f"Category margin for {ctx.product_category}: {m:.1%}",
        )
    return ResolvedMargin(
        margin_pct=Decimal("0.20"),
        rule_name="org_default",
        explanation="Default organization margin: 20%",
    )
