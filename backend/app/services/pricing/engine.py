"""
Pricing engine — deterministic calculation of unit prices and totals.

All math lives here. LLMs propose, this engine computes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class LandedCostInputs:
    supplier_unit_price: Decimal
    supplier_currency: str
    quote_currency: str
    fx_rate: Decimal  # supplier_ccy → quote_ccy
    logistics_per_unit: Decimal = Decimal("0")
    duties_per_unit: Decimal = Decimal("0")
    handling_per_unit: Decimal = Decimal("0")
    fx_cost_pct: Decimal = Decimal("0.002")  # 0.2% bank spread default
    payment_term_cost: Decimal = Decimal("0")
    risk_reserve: Decimal = Decimal("0")


@dataclass
class LandedCost:
    components: dict[str, Decimal]
    total: Decimal


def calculate_landed_cost(i: LandedCostInputs) -> LandedCost:
    """Compute landed cost per unit in quote currency."""
    base = i.supplier_unit_price * i.fx_rate
    fx_cost = base * i.fx_cost_pct
    components = {
        "supplier_base": base,
        "logistics": i.logistics_per_unit,
        "duties": i.duties_per_unit,
        "handling": i.handling_per_unit,
        "fx_cost": fx_cost,
        "payment_term": i.payment_term_cost,
        "risk_reserve": i.risk_reserve,
    }
    total = sum(components.values(), Decimal("0"))
    return LandedCost(components=components, total=total)


@dataclass
class PricingResult:
    unit_price: Decimal
    unit_cost: Decimal
    margin_amount: Decimal
    margin_pct: Decimal
    applied_rule: str  # which rule won (for transparency in UI)


def calculate_unit_price(
    *,
    landed_cost: Decimal,
    margin_pct: Decimal,
    override_price: Decimal | None = None,
    applied_rule: str = "default_margin",
) -> PricingResult:
    """
    sell_price = cost / (1 - margin_pct) for margin-on-sell-price (standard B2B).
    Use override_price when manually set.
    """
    if override_price is not None:
        unit_price = override_price
        applied_rule = "manual_override"
    else:
        if margin_pct >= 1:
            raise ValueError("margin_pct must be < 1 (e.g. 0.18 for 18%)")
        unit_price = (landed_cost / (Decimal("1") - margin_pct)).quantize(Decimal("0.0001"))

    margin_amount = unit_price - landed_cost
    actual_margin_pct = (margin_amount / unit_price) if unit_price else Decimal("0")
    return PricingResult(
        unit_price=unit_price,
        unit_cost=landed_cost,
        margin_amount=margin_amount,
        margin_pct=actual_margin_pct,
        applied_rule=applied_rule,
    )
