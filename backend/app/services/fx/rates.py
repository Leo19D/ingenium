"""
FX tečajevi — ECB dnevni tečajevi s cacheom + statički fallback.

ECB objavljuje besplatan XML (baza EUR). Konverzija između bilo koje dvije
valute ide preko EUR. Ako ECB nije dostupan (offline), koristi statički
fallback (approx tečajevi) da sustav nikad ne stane.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

import httpx

logger = logging.getLogger(__name__)

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

# Statički fallback (EUR baza) — approx, koristi se samo ako ECB padne
_FALLBACK_EUR = {
    "EUR": Decimal("1"), "USD": Decimal("1.08"), "GBP": Decimal("0.85"),
    "CHF": Decimal("0.96"), "PLN": Decimal("4.30"), "CZK": Decimal("25.0"),
    "HUF": Decimal("395"), "RON": Decimal("4.97"), "SEK": Decimal("11.3"),
    "NOK": Decimal("11.5"), "DKK": Decimal("7.46"), "JPY": Decimal("162"),
    "CNY": Decimal("7.85"), "HRK": Decimal("7.53"),  # HRK fiksni (povijesni)
}

# Cache: {currency: rate_to_eur}, osvježava se svakih nekoliko sati
_cache: dict[str, Decimal] = {}
_cache_time: datetime | None = None
_CACHE_TTL_SECONDS = 6 * 3600


async def _fetch_ecb() -> dict[str, Decimal] | None:
    """Dohvati ECB dnevne tečajeve (baza EUR). None na grešku."""
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(ECB_URL)
            r.raise_for_status()
            text = r.text
        # Parse XML bez ovisnosti — traži <Cube currency="USD" rate="1.08"/>
        import re
        rates: dict[str, Decimal] = {"EUR": Decimal("1")}
        for m in re.finditer(r'currency=[\'"]([A-Z]{3})[\'"]\s+rate=[\'"]([\d.]+)[\'"]', text):
            rates[m.group(1)] = Decimal(m.group(2))
        return rates if len(rates) > 1 else None
    except Exception as e:
        logger.warning("ecb_fetch_failed", extra={"error": str(e)})
        return None


async def _rates_eur_base() -> tuple[dict[str, Decimal], str]:
    """Vrati (tečajevi EUR-baza, izvor). Cache → ECB → fallback."""
    global _cache, _cache_time
    now = datetime.now(UTC)
    if _cache and _cache_time and (now - _cache_time).total_seconds() < _CACHE_TTL_SECONDS:
        return _cache, "cache"

    ecb = await _fetch_ecb()
    if ecb:
        _cache = ecb
        _cache_time = now
        return ecb, "ecb"

    return dict(_FALLBACK_EUR), "fallback"


async def convert(amount: Decimal, base: str, quote: str) -> dict:
    """
    Konvertiraj `amount` iz `base` valute u `quote` valutu.
    Vraća {amount, rate, base, quote, source, as_of}.
    """
    base = base.upper().strip()
    quote = quote.upper().strip()
    if base == quote:
        return {"amount": amount, "rate": Decimal("1"), "base": base, "quote": quote,
                "source": "identity", "as_of": datetime.now(UTC).isoformat()}

    rates, source = await _rates_eur_base()
    r_base = rates.get(base)
    r_quote = rates.get(quote)
    if r_base is None or r_quote is None:
        # Nepoznata valuta — vrati nepromijenjeno s rate 1, flag
        return {"amount": amount, "rate": Decimal("1"), "base": base, "quote": quote,
                "source": "unsupported", "as_of": datetime.now(UTC).isoformat()}

    # base→EUR→quote: rate = r_quote / r_base
    rate = (r_quote / r_base).quantize(Decimal("0.00000001"))
    converted = (amount * rate).quantize(Decimal("0.01"))
    return {"amount": converted, "rate": rate, "base": base, "quote": quote,
            "source": source, "as_of": datetime.now(UTC).isoformat()}


async def get_rate(base: str, quote: str) -> dict:
    """Samo tečaj (bez iznosa)."""
    res = await convert(Decimal("1"), base, quote)
    return {"base": res["base"], "quote": res["quote"], "rate": res["rate"],
            "source": res["source"], "as_of": res["as_of"]}
