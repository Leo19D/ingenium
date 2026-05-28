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

from app.core.security import decode_token
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
    try:
        payload = decode_token(token)
    except JWTError:
        raise credentials_exc

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
        )
    org_str = payload.get("org")
    if not org_str:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token ne sadrži org.")
    return UUID(org_str)
