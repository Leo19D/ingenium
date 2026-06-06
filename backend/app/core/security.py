"""JWT tokens, bcrypt password utilities, OTP, rate limiter, token blacklist."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from time import time
from typing import Any

import bcrypt
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

# --------------------------------------------------------------------------- #
# Password                                                                     #
# --------------------------------------------------------------------------- #

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def validate_password_strength(password: str) -> str | None:
    """Return error message if password is too weak, else None."""
    if len(password) < 8:
        return "Lozinka mora imati najmanje 8 znakova."
    if not any(c.isdigit() for c in password):
        return "Lozinka mora sadržavati najmanje jednu znamenku."
    if not any(c.isalpha() for c in password):
        return "Lozinka mora sadržavati najmanje jedno slovo."
    return None


# --------------------------------------------------------------------------- #
# JWT                                                                          #
# --------------------------------------------------------------------------- #

def create_access_token(user_id: str, org_id: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "org": org_id, "type": "access", "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "type": "refresh", "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify JWT. Raises jose.JWTError on invalid/expired tokens."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


# --------------------------------------------------------------------------- #
# OTP (email 2FA)                                                             #
# --------------------------------------------------------------------------- #

OTP_LENGTH = 6
OTP_EXPIRE_SECONDS = 120  # 2 minute
OTP_MAX_ATTEMPTS = 3


def generate_otp() -> str:
    """Generate a cryptographically random 6-digit OTP."""
    return f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"


def hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def verify_otp_hash(code: str, stored_hash: str) -> bool:
    return secrets.compare_digest(hash_otp(code), stored_hash)


# --------------------------------------------------------------------------- #
# Token blacklist — DB-backed (preživi restart i dijeli se među workerima)     #
# --------------------------------------------------------------------------- #

def hash_token(token: str) -> str:
    """SHA-256 hex tokena — ne spremamo sirovi token u bazu."""
    return hashlib.sha256(token.encode()).hexdigest()


async def revoke_token(db: AsyncSession, token: str) -> None:
    """Poništi (blacklistaj) access token do njegovog isteka."""
    from app.db.models.security import RevokedToken

    ttl = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    # merge = idempotentno (dvostruka odjava ne ruši constraint)
    await db.merge(RevokedToken(token_hash=hash_token(token), expires_epoch=time() + ttl))
    await db.commit()


async def is_token_revoked(db: AsyncSession, token: str) -> bool:
    from app.db.models.security import RevokedToken

    row = await db.get(RevokedToken, hash_token(token))
    return bool(row and row.expires_epoch > time())


async def purge_expired_security_rows(db: AsyncSession) -> None:
    """Očisti istekle blacklist tokene i stare login pokušaje (zove scheduler)."""
    from sqlalchemy import delete

    from app.db.models.security import LoginAttempt, RevokedToken

    now = time()
    await db.execute(delete(RevokedToken).where(RevokedToken.expires_epoch <= now))
    await db.execute(delete(LoginAttempt).where(LoginAttempt.created_epoch <= now - 3600))
    await db.commit()


# --------------------------------------------------------------------------- #
# Login rate limiter — DB-backed sliding window, per IP                        #
# --------------------------------------------------------------------------- #

_RATE_MAX_ATTEMPTS = 5
_RATE_WINDOW_SECONDS = 60


async def check_login_rate(
    db: AsyncSession,
    ip: str,
    *,
    max_attempts: int = _RATE_MAX_ATTEMPTS,
    window: int = _RATE_WINDOW_SECONDS,
) -> tuple[bool, int]:
    """Vrati (dopušteno, sekundi_do_resetiranja). Bilježi pokušaj ako je dopušten."""
    from sqlalchemy import select

    from app.db.models.security import LoginAttempt

    now = time()
    cutoff = now - window
    recent = (
        await db.execute(
            select(LoginAttempt.created_epoch)
            .where(LoginAttempt.ip == ip, LoginAttempt.created_epoch > cutoff)
            .order_by(LoginAttempt.created_epoch)
        )
    ).scalars().all()

    if len(recent) >= max_attempts:
        retry = max(0, int(window - (now - recent[0]))) + 1
        return False, retry

    db.add(LoginAttempt(ip=ip, created_epoch=now))
    await db.commit()
    return True, 0
