"""JWT tokens, bcrypt password utilities, OTP, rate limiter, token blacklist."""

from __future__ import annotations

import hashlib
import secrets
import threading
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

import bcrypt
from jose import jwt

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
# Token blacklist (in-memory, TTL = access token lifetime)                    #
# --------------------------------------------------------------------------- #

class _TokenBlacklist:
    """Thread-safe in-memory set of revoked tokens with auto-expiry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # token → expiry monotonic timestamp
        self._store: dict[str, float] = {}
        self._last_cleanup = monotonic()

    def add(self, token: str) -> None:
        ttl = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
        expiry = monotonic() + ttl
        with self._lock:
            self._store[token] = expiry
            self._maybe_cleanup()

    def contains(self, token: str) -> bool:
        now = monotonic()
        with self._lock:
            expiry = self._store.get(token)
            if expiry is None:
                return False
            if now > expiry:
                del self._store[token]
                return False
            return True

    def _maybe_cleanup(self) -> None:
        now = monotonic()
        if now - self._last_cleanup < 300:
            return
        self._last_cleanup = now
        expired = [t for t, exp in self._store.items() if now > exp]
        for t in expired:
            del self._store[t]


_blacklist = _TokenBlacklist()


def blacklist_token(token: str) -> None:
    _blacklist.add(token)


def is_token_blacklisted(token: str) -> bool:
    return _blacklist.contains(token)


# --------------------------------------------------------------------------- #
# Login rate limiter (sliding window, per IP)                                 #
# --------------------------------------------------------------------------- #

class _RateLimiter:
    """Thread-safe sliding-window rate limiter."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 60) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._lock = threading.Lock()
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = monotonic()
        cutoff = now - self._window
        with self._lock:
            hits = self._attempts[key]
            recent = [t for t in hits if t > cutoff]
            self._attempts[key] = recent
            if len(recent) >= self._max:
                return False
            recent.append(now)
            return True

    def seconds_until_reset(self, key: str) -> int:
        now = monotonic()
        cutoff = now - self._window
        with self._lock:
            hits = [t for t in self._attempts.get(key, []) if t > cutoff]
            if not hits:
                return 0
            oldest = min(hits)
            return max(0, int(self._window - (now - oldest))) + 1


login_rate_limiter = _RateLimiter(max_attempts=5, window_seconds=60)
