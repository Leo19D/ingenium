"""
Reusable FastAPI dependencies.

get_current_user    — dekodira Bearer JWT, vraća User objekt
get_current_org_id  — izvlači org UUID iz JWT (brzo, bez DB)
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token, is_token_blacklisted
from app.db.models.user import User
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Provjeri Bearer token i vrati korisnika. 401 ako nije valjan."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Niste prijavljeni ili je sesija istekla.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if is_token_blacklisted(token):
        raise credentials_exc

    try:
        payload = decode_token(token)
    except JWTError:
        raise credentials_exc from None

    if payload.get("type") != "access":
        raise credentials_exc

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise credentials_exc

    user = await db.get(User, UUID(user_id_str))
    if not user or not user.is_active or not user.is_verified:
        raise credentials_exc
    return user


async def get_current_org_id(
    token: str = Depends(oauth2_scheme),
) -> UUID:
    """Izvuci org_id iz JWT-a (bez DB poziva)."""
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Niste prijavljeni ili je sesija istekla.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    org_str = payload.get("org")
    if not org_str:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token ne sadrži org.")
    return UUID(org_str)


# ── Role-based access ────────────────────────────────────────────────────────

# Hijerarhija — viša rola obuhvaća prava nižih
ROLE_RANK = {"viewer": 0, "sales": 1, "procurement": 1, "approver": 2, "admin": 3, "owner": 4}


async def get_current_role(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Vrati rolu trenutnog korisnika u njegovoj org. Default 'viewer'."""
    from sqlalchemy import select

    from app.db.models.user import Membership

    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Sesija istekla.") from None
    user_id = payload.get("sub")
    org_id = payload.get("org")
    if not user_id or not org_id:
        return "viewer"
    m = await db.scalar(
        select(Membership).where(
            Membership.user_id == UUID(user_id),
            Membership.org_id == UUID(org_id),
        )
    )
    return m.role if m else "viewer"


def require_role(min_role: str):
    """Dependency factory — traži barem `min_role` (po ROLE_RANK hijerarhiji)."""
    min_rank = ROLE_RANK.get(min_role, 0)

    async def _check(role: str = Depends(get_current_role)) -> str:
        if ROLE_RANK.get(role, 0) < min_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Nedovoljna prava — potrebna rola '{min_role}' ili viša (vaša: '{role}').",
            )
        return role

    return _check
