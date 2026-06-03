"""Team members — lista, pozivanje, role, uklanjanje. Samo admin/owner."""

from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ROLE_RANK, get_current_org_id, get_current_user, require_role
from app.core.security import generate_verification_token, hash_password
from app.db.models.organization import Organization
from app.db.models.user import Membership, User
from app.db.session import get_db
from app.services.email.smtp import send_email

router = APIRouter()

VALID_ROLES = {"owner", "admin", "approver", "sales", "procurement", "viewer"}
_ALLOWED_DOMAIN = "ingeniumtrade.hr"
_ADMIN_EMAIL = "leodupanovic1@gmail.com"


def _is_allowed(email: str) -> bool:
    e = email.lower().strip()
    return e == _ADMIN_EMAIL or e.endswith(f"@{_ALLOWED_DOMAIN}")


class MemberResponse(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    role: str
    is_verified: bool


class InviteRequest(BaseModel):
    email: EmailStr
    full_name: str
    role: str = "sales"


class RoleUpdate(BaseModel):
    role: str


@router.get("/", response_model=list[MemberResponse])
async def list_members(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> list[MemberResponse]:
    """Svi članovi organizacije s rolama."""
    rows = await db.execute(
        select(User, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org_id)
        .order_by(User.full_name)
    )
    return [
        MemberResponse(
            user_id=u.id, email=u.email, full_name=u.full_name,
            role=role, is_verified=u.is_verified,
        )
        for u, role in rows.all()
    ]


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_member(
    req: InviteRequest,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    _: str = Depends(require_role("admin")),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Pozovi korisnika u organizaciju. Samo admin/owner. Šalje invite email."""
    email = req.email.lower().strip()
    if req.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"Nevaljana rola. Dozvoljeno: {', '.join(VALID_ROLES)}")
    if not _is_allowed(email):
        raise HTTPException(status_code=403, detail="Email nije dozvoljen za ovu organizaciju.")

    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        # Već postoji — provjeri ima li membership u ovoj org
        m = await db.scalar(
            select(Membership).where(Membership.user_id == existing.id, Membership.org_id == org_id)
        )
        if m:
            raise HTTPException(status_code=409, detail="Korisnik je već član organizacije.")
        db.add(Membership(org_id=org_id, user_id=existing.id, role=req.role))
        await db.commit()
        return {"message": f"{email} dodan u organizaciju kao {req.role}.", "status": "added"}

    # Novi korisnik — kreiraj s privremenom lozinkom + verifikacijski token
    temp_password = secrets.token_urlsafe(12)
    token = generate_verification_token()
    user = User(
        email=email, full_name=req.full_name.strip(), auth_provider="local",
        hashed_password=hash_password(temp_password), is_active=True, is_verified=False,
        verification_token=token,
    )
    db.add(user)
    await db.flush()
    db.add(Membership(org_id=org_id, user_id=user.id, role=req.role))
    await db.commit()

    org = await db.scalar(select(Organization).where(Organization.id == org_id))
    org_name = org.name if org else "Ingenium"
    try:
        await send_email(
            to=email,
            subject=f"Pozvani ste u {org_name} — Ingenium",
            html=_invite_html(req.full_name, org_name, req.role, current_user.full_name, temp_password),
        )
    except Exception:
        pass

    return {"message": f"Poziv poslan na {email} (rola: {req.role}).", "status": "invited"}


@router.patch("/{user_id}/role", response_model=MemberResponse)
async def change_role(
    user_id: UUID,
    req: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    actor_role: str = Depends(require_role("admin")),
    current_user: User = Depends(get_current_user),
) -> MemberResponse:
    """Promijeni rolu člana. Samo admin/owner. Ne možeš dodijeliti rolu višu od svoje."""
    if req.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail="Nevaljana rola.")
    if ROLE_RANK.get(req.role, 0) > ROLE_RANK.get(actor_role, 0):
        raise HTTPException(status_code=403, detail="Ne možeš dodijeliti rolu višu od svoje.")

    m = await db.scalar(
        select(Membership).where(Membership.user_id == user_id, Membership.org_id == org_id)
    )
    if not m:
        raise HTTPException(status_code=404, detail="Član nije pronađen.")
    if user_id == current_user.id and m.role in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Ne možeš sebi smanjiti rolu (admin/owner).")

    m.role = req.role
    await db.commit()
    u = await db.get(User, user_id)
    return MemberResponse(user_id=u.id, email=u.email, full_name=u.full_name,
                          role=m.role, is_verified=u.is_verified)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    _: str = Depends(require_role("admin")),
    current_user: User = Depends(get_current_user),
) -> None:
    """Ukloni člana iz organizacije. Samo admin/owner. Ne možeš sebe."""
    if user_id == current_user.id:
        raise HTTPException(status_code=403, detail="Ne možeš ukloniti sebe.")
    m = await db.scalar(
        select(Membership).where(Membership.user_id == user_id, Membership.org_id == org_id)
    )
    if not m:
        raise HTTPException(status_code=404, detail="Član nije pronađen.")
    await db.delete(m)
    await db.commit()


def _invite_html(name: str, org_name: str, role: str, inviter: str, temp_pw: str) -> str:
    return f"""<!DOCTYPE html><html lang="hr"><body style="margin:0;background:#f4f7fb;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#f4f7fb"><tr><td align="center" style="padding:48px 16px">
  <table width="500" cellpadding="0" cellspacing="0" bgcolor="#f8fafc" style="border-radius:14px;border:1px solid #d4dde9;overflow:hidden">
    <tr><td bgcolor="#1a5699" height="4"></td></tr>
    <tr><td style="padding:36px 40px">
      <h1 style="margin:0 0 8px;font-size:20px;color:#1b2940">Pozvani ste u {org_name}</h1>
      <p style="margin:0 0 20px;font-size:14px;color:#586780;line-height:1.6">
        Pozdrav {name}, <strong>{inviter}</strong> vas je pozvao/la da se pridružite
        organizaciji <strong>{org_name}</strong> na Ingenium platformi s rolom <strong>{role}</strong>.
      </p>
      <table cellpadding="0" cellspacing="0" bgcolor="#eef4ff" style="border-radius:8px;width:100%">
        <tr><td style="padding:14px 18px;font-size:13px;color:#586780">
          Privremena lozinka:<br><strong style="font-family:monospace;font-size:15px;color:#1a5699">{temp_pw}</strong><br>
          <span style="font-size:12px">Prijavite se i promijenite je. Email morate prvo potvrditi.</span>
        </td></tr>
      </table>
      <p style="margin:20px 0 0;font-size:12px;color:#93a1b4">Ingenium · AI Quote &amp; Procurement Platform</p>
    </td></tr>
  </table>
</td></tr></table></body></html>"""
