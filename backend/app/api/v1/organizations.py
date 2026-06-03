"""Organization settings — postavke firme (naziv, VAT, marže, approval limiti)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.db.models.organization import Organization
from app.db.session import get_db

router = APIRouter()


# Defaultne postavke ako org.settings nema vrijednost
DEFAULT_SETTINGS = {
    "vat_id": "",
    "category_margins": {},          # {"led_panel": 0.18, "kabel": 0.08, ...}
    "default_margin_pct": 0.25,
    "approval_threshold": 5000,
    "dual_approval_threshold": 50000,
    "min_margin_pct": 0.05,
}


class OrgSettingsResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    country_code: str
    base_currency: str
    vat_id: str
    category_margins: dict
    default_margin_pct: float
    approval_threshold: float
    dual_approval_threshold: float
    min_margin_pct: float


class OrgSettingsUpdate(BaseModel):
    name: str | None = None
    country_code: str | None = None
    base_currency: str | None = None
    vat_id: str | None = None
    category_margins: dict | None = None
    default_margin_pct: float | None = Field(default=None, ge=0, le=0.95)
    approval_threshold: float | None = Field(default=None, ge=0)
    dual_approval_threshold: float | None = Field(default=None, ge=0)
    min_margin_pct: float | None = Field(default=None, ge=0, le=1)


def _merged(org: Organization) -> dict:
    """Spoji default postavke s org.settings."""
    s = dict(DEFAULT_SETTINGS)
    s.update(org.settings or {})
    return s


def _to_response(org: Organization) -> OrgSettingsResponse:
    s = _merged(org)
    return OrgSettingsResponse(
        id=org.id, name=org.name, slug=org.slug,
        country_code=org.country_code, base_currency=org.base_currency,
        vat_id=s["vat_id"], category_margins=s["category_margins"],
        default_margin_pct=s["default_margin_pct"],
        approval_threshold=s["approval_threshold"],
        dual_approval_threshold=s["dual_approval_threshold"],
        min_margin_pct=s["min_margin_pct"],
    )


async def get_org_limits(db: AsyncSession, org_id: UUID) -> dict:
    """Helper za approval logiku — vrati limite kao Decimal + seller info."""
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    s = _merged(org) if org else dict(DEFAULT_SETTINGS)
    return {
        "approval_threshold": Decimal(str(s["approval_threshold"])),
        "dual_approval_threshold": Decimal(str(s["dual_approval_threshold"])),
        "min_margin_pct": Decimal(str(s["min_margin_pct"])),
        "seller_country": org.country_code if org else "HR",
        "vat_id": s["vat_id"],
    }


@router.get("/current", response_model=OrgSettingsResponse)
async def get_current_org(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> OrgSettingsResponse:
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organizacija nije pronađena.")
    return _to_response(org)


@router.put("/current", response_model=OrgSettingsResponse)
async def update_current_org(
    req: OrgSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> OrgSettingsResponse:
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organizacija nije pronađena.")

    if req.name is not None:
        org.name = req.name.strip()
    if req.country_code is not None:
        org.country_code = req.country_code.strip().upper()[:2]
    if req.base_currency is not None:
        org.base_currency = req.base_currency.strip().upper()[:3]

    s = dict(org.settings or {})
    for field in ("vat_id", "category_margins", "default_margin_pct",
                  "approval_threshold", "dual_approval_threshold", "min_margin_pct"):
        val = getattr(req, field)
        if val is not None:
            s[field] = val
    org.settings = s
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(org, "settings")

    await db.commit()
    await db.refresh(org)
    return _to_response(org)


# ─────────────────────────────────────────────────────────────────────────────
# Setovi stavki (quote item templates) — spremljeni česti setovi
# ─────────────────────────────────────────────────────────────────────────────

class ItemTemplate(BaseModel):
    name: str
    items: list[dict]  # [{description, quantity, unit, unit_price, unit_cost?}]


@router.get("/item-templates")
async def list_item_templates(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> list[dict]:
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    return (org.settings or {}).get("item_templates", []) if org else []


@router.post("/item-templates", status_code=201)
async def save_item_template(
    req: ItemTemplate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> dict:
    from sqlalchemy.orm.attributes import flag_modified

    if not req.name.strip() or not req.items:
        raise HTTPException(status_code=422, detail="Naziv i barem jedna stavka su obavezni.")
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organizacija nije pronađena.")
    s = dict(org.settings or {})
    templates = [t for t in s.get("item_templates", []) if t.get("name") != req.name.strip()]
    templates.append({"name": req.name.strip(), "items": req.items})
    s["item_templates"] = templates
    org.settings = s
    flag_modified(org, "settings")
    await db.commit()
    return {"message": f"Set '{req.name}' spremljen ({len(req.items)} stavki).", "count": len(templates)}


@router.delete("/item-templates/{name}", status_code=204)
async def delete_item_template(
    name: str,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> None:
    from sqlalchemy.orm.attributes import flag_modified

    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organizacija nije pronađena.")
    s = dict(org.settings or {})
    s["item_templates"] = [t for t in s.get("item_templates", []) if t.get("name") != name]
    org.settings = s
    flag_modified(org, "settings")
    await db.commit()
