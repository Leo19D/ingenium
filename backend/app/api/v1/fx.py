"""FX — tečajevi i konverzija (ECB + fallback)."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends

from app.api.deps import get_current_org_id
from app.services.fx.rates import convert, get_rate

router = APIRouter()


@router.get("/rate")
async def fx_rate(base: str, quote: str = "EUR", _=Depends(get_current_org_id)) -> dict:
    """Tečaj base→quote. Npr. /fx/rate?base=USD&quote=EUR"""
    r = await get_rate(base, quote)
    r["rate"] = float(r["rate"])
    return r


@router.get("/convert")
async def fx_convert(
    amount: float, base: str, quote: str = "EUR", _=Depends(get_current_org_id)
) -> dict:
    """Konvertiraj iznos. Npr. /fx/convert?amount=100&base=USD&quote=EUR"""
    r = await convert(Decimal(str(amount)), base, quote)
    r["amount"] = float(r["amount"])
    r["rate"] = float(r["rate"])
    return r
