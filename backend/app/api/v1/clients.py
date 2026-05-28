"""Clients API endpoints — CRUD + bulk import iz Excela."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.db.models.client import Client
from app.db.session import get_db
from app.schemas.client import (
    BulkImportResult,
    ClientBulkImportRequest,
    ClientCreate,
    ClientResponse,
    ClientUpdate,
)

router = APIRouter()


# Mapiranje "punih naziva" zemalja iz Excela na ISO-2 kodove
COUNTRY_NAME_TO_CODE = {
    "hrvatska": "HR", "croatia": "HR",
    "slovenija": "SI", "slovenia": "SI",
    "bosna i hercegovina": "BA", "bih": "BA", "bosnia": "BA",
    "srbija": "RS", "serbia": "RS",
    "austrija": "AT", "austria": "AT",
    "njemacka": "DE", "njemačka": "DE", "germany": "DE", "deutschland": "DE",
    "italija": "IT", "italy": "IT", "italia": "IT",
    "francuska": "FR", "france": "FR",
    "spanjolska": "ES", "španjolska": "ES", "spain": "ES",
    "nizozemska": "NL", "netherlands": "NL",
    "svedska": "SE", "švedska": "SE", "sweden": "SE",
    "rumunjska": "RO", "romania": "RO",
    "poljska": "PL", "poland": "PL",
    "madjarska": "HU", "mađarska": "HU", "hungary": "HU",
    "kina": "CN", "china": "CN",
}


def _normalize_country_code(value: str | None) -> str:
    """Excel može imati 'Hrvatska', 'HR', 'Njemačka (DE)' — sve mapira na HR/DE/..."""
    if not value:
        return "HR"
    s = str(value).strip()
    # Parens npr. "Njemačka (DE)" → DE
    if "(" in s and ")" in s:
        try:
            inner = s[s.index("(") + 1 : s.index(")")].strip().upper()
            if len(inner) == 2 and inner.isalpha():
                return inner
        except ValueError:
            pass
    # Već je ISO-2
    if len(s) == 2 and s.isalpha():
        return s.upper()
    # Puni naziv
    return COUNTRY_NAME_TO_CODE.get(s.lower(), s[:2].upper())


def _parse_int(value: str | None, default: int = 30) -> int:
    if not value:
        return default
    try:
        return int(float(str(value).strip().replace(",", ".")))
    except (ValueError, TypeError):
        return default


@router.get("/", response_model=list[ClientResponse])
async def list_clients(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> list[Client]:
    """Lista svih klijenata u trenutnoj organizaciji."""
    result = await db.execute(
        select(Client).where(Client.org_id == org_id).order_by(Client.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> Client:
    result = await db.execute(
        select(Client).where(Client.id == client_id, Client.org_id == org_id)
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Klijent ne postoji")
    return client


@router.post("/", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> Client:
    client = Client(org_id=org_id, **payload.model_dump())
    db.add(client)
    try:
        await db.flush()
        await db.refresh(client)
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Klijent s ovim OIB-om već postoji: {payload.tax_id}",
        ) from e
    return client


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: UUID,
    payload: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> Client:
    result = await db.execute(
        select(Client).where(Client.id == client_id, Client.org_id == org_id)
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Klijent ne postoji")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(client, k, v)
    await db.flush()
    await db.refresh(client)
    return client


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> None:
    result = await db.execute(
        select(Client).where(Client.id == client_id, Client.org_id == org_id)
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Klijent ne postoji")
    await db.delete(client)


@router.post("/bulk", response_model=BulkImportResult, status_code=status.HTTP_201_CREATED)
async def bulk_import_clients(
    payload: ClientBulkImportRequest,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> BulkImportResult:
    """Bulk uvoz klijenata iz Excela.

    Mapira polja s relaxed schemom (naziv, vat, country, segment, payment),
    preskoči duplikate po (org_id, tax_id).
    """
    inserted = 0
    skipped = 0
    errors: list[str] = []

    for idx, item in enumerate(payload.items):
        try:
            if not item.naziv or not item.naziv.strip():
                skipped += 1
                continue
            country_code = _normalize_country_code(item.country)
            segment = (item.segment or "").lower().split("/")[0].strip() or None
            client = Client(
                org_id=org_id,
                name=item.naziv.strip(),
                tax_id=(item.vat or "").strip() or None,
                country_code=country_code,
                segment=segment,
                payment_terms_days=_parse_int(item.payment, 30),
            )
            db.add(client)
            await db.flush()
            inserted += 1
        except IntegrityError:
            await db.rollback()
            skipped += 1
        except Exception as e:  # noqa: BLE001
            await db.rollback()
            errors.append(f"Red {idx + 1}: {type(e).__name__}: {e}")
            skipped += 1

    return BulkImportResult(inserted=inserted, skipped=skipped, errors=errors)
