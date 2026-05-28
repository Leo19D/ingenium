"""
Tax engine — pluggable per jurisdiction.

Tax is a matrix of (jurisdiction × transaction type × goods type × buyer status).
This module picks the right rule and returns the computed tax.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class TaxContext:
    seller_country: str
    seller_vat_id: str | None
    buyer_country: str
    buyer_vat_id: str | None
    buyer_is_business: bool
    region: str | None = None  # US state, etc.
    goods_type: str | None = None  # for category-specific rules


@dataclass
class TaxResult:
    rate: Decimal
    amount: Decimal
    rule_name: str
    explanation: str
    is_reverse_charge: bool = False


class TaxEngine:
    """Dispatches to jurisdiction-specific handlers."""

    async def calculate(self, line_total: Decimal, ctx: TaxContext) -> TaxResult:
        # EU B2B intra-community with valid VAT ID → reverse charge
        if (
            self._is_eu(ctx.seller_country)
            and self._is_eu(ctx.buyer_country)
            and ctx.seller_country != ctx.buyer_country
            and ctx.buyer_is_business
            and ctx.buyer_vat_id
        ):
            return TaxResult(
                rate=Decimal("0"),
                amount=Decimal("0"),
                rule_name="eu_b2b_reverse_charge",
                explanation="EU B2B intra-community supply with valid VAT ID — reverse charge",
                is_reverse_charge=True,
            )

        # Domestic EU → standard VAT (TODO: load actual rate from tax_rules)
        if ctx.seller_country == ctx.buyer_country and self._is_eu(ctx.seller_country):
            rate = self._get_standard_vat(ctx.seller_country)
            return TaxResult(
                rate=rate,
                amount=(line_total * rate).quantize(Decimal("0.01")),
                rule_name=f"vat_domestic_{ctx.seller_country.lower()}",
                explanation=f"Domestic VAT for {ctx.seller_country}: {rate:.1%}",
            )

        # Export outside EU → zero-rated
        if self._is_eu(ctx.seller_country) and not self._is_eu(ctx.buyer_country):
            return TaxResult(
                rate=Decimal("0"),
                amount=Decimal("0"),
                rule_name="export_zero_rated",
                explanation="Export outside EU — zero-rated (documentation required)",
            )

        # US — placeholder, real impl uses TaxJar/Avalara
        if ctx.seller_country == "US":
            return TaxResult(
                rate=Decimal("0"),
                amount=Decimal("0"),
                rule_name="us_sales_tax_TODO",
                explanation="US sales tax requires nexus + per-state lookup (TODO)",
            )

        return TaxResult(
            rate=Decimal("0"),
            amount=Decimal("0"),
            rule_name="unknown",
            explanation=f"No rule matched for {ctx.seller_country} → {ctx.buyer_country}",
        )

    @staticmethod
    def _is_eu(country: str) -> bool:
        EU = {
            "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
            "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
            "PL", "PT", "RO", "SK", "SI", "ES", "SE",
        }
        return country.upper() in EU

    @staticmethod
    def _get_standard_vat(country: str) -> Decimal:
        # Highly simplified — load from DB in production
        rates = {
            "HR": Decimal("0.25"), "DE": Decimal("0.19"), "FR": Decimal("0.20"),
            "IT": Decimal("0.22"), "ES": Decimal("0.21"), "NL": Decimal("0.21"),
            "BE": Decimal("0.21"), "AT": Decimal("0.20"), "PL": Decimal("0.23"),
            "SE": Decimal("0.25"), "FI": Decimal("0.24"), "IE": Decimal("0.23"),
            "PT": Decimal("0.23"), "GR": Decimal("0.24"), "CZ": Decimal("0.21"),
            "SK": Decimal("0.20"), "SI": Decimal("0.22"), "HU": Decimal("0.27"),
            "RO": Decimal("0.19"), "BG": Decimal("0.20"), "EE": Decimal("0.22"),
            "LV": Decimal("0.21"), "LT": Decimal("0.21"), "LU": Decimal("0.17"),
            "MT": Decimal("0.18"), "CY": Decimal("0.19"), "DK": Decimal("0.25"),
        }
        return rates.get(country.upper(), Decimal("0.20"))
