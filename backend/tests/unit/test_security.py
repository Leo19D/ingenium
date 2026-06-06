"""Unit testovi za security.py — JWT i bcrypt."""

from __future__ import annotations

import pytest
from jose import JWTError

from app.core.security import (
    check_login_rate,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_verification_token,
    hash_password,
    is_token_revoked,
    revoke_token,
    validate_password_strength,
    verify_password,
)


@pytest.mark.unit
def test_password_hash_and_verify():
    hashed = hash_password("mojalozinka123")
    assert verify_password("mojalozinka123", hashed)
    assert not verify_password("pogresna", hashed)


@pytest.mark.unit
def test_access_token_decode():
    token = create_access_token("user-123", "org-456")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["org"] == "org-456"
    assert payload["type"] == "access"


@pytest.mark.unit
def test_refresh_token_decode():
    token = create_refresh_token("user-123")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["type"] == "refresh"
    assert "org" not in payload


@pytest.mark.unit
def test_decode_invalid_token_raises():
    with pytest.raises(JWTError):
        decode_token("ovo.nije.valjan.token")


@pytest.mark.unit
def test_verification_token_is_urlsafe():
    token = generate_verification_token()
    assert len(token) >= 40
    assert all(c not in token for c in ["+", "/", "="])


@pytest.mark.unit
def test_password_strength_too_short():
    assert validate_password_strength("abc1") is not None


@pytest.mark.unit
def test_password_strength_no_digit():
    assert validate_password_strength("abcdefgh") is not None


@pytest.mark.unit
def test_password_strength_no_letter():
    assert validate_password_strength("12345678") is not None


@pytest.mark.unit
def test_password_strength_valid():
    assert validate_password_strength("lozinka1") is None
    assert validate_password_strength("Secur3Pass!") is None


@pytest.mark.asyncio
async def test_token_revoke_and_check(db_session):
    token = create_access_token("u1", "o1")
    assert not await is_token_revoked(db_session, token)
    await revoke_token(db_session, token)
    assert await is_token_revoked(db_session, token)
    # Idempotentno — dvostruka odjava ne smije pući
    await revoke_token(db_session, token)
    assert await is_token_revoked(db_session, token)


@pytest.mark.asyncio
async def test_other_token_not_revoked(db_session):
    revoked = create_access_token("u1", "o1")
    other = create_access_token("u2", "o1")
    await revoke_token(db_session, revoked)
    assert not await is_token_revoked(db_session, other)


@pytest.mark.asyncio
async def test_rate_limiter_allows_under_limit(db_session):
    for _ in range(3):
        allowed, _wait = await check_login_rate(db_session, "ip-a", max_attempts=3)
        assert allowed


@pytest.mark.asyncio
async def test_rate_limiter_blocks_over_limit(db_session):
    for _ in range(3):
        await check_login_rate(db_session, "ip-b", max_attempts=3)
    allowed, wait = await check_login_rate(db_session, "ip-b", max_attempts=3)
    assert not allowed
    assert wait > 0


@pytest.mark.asyncio
async def test_rate_limiter_independent_keys(db_session):
    for _ in range(2):
        await check_login_rate(db_session, "ip-x", max_attempts=2)
    blocked, _ = await check_login_rate(db_session, "ip-x", max_attempts=2)
    assert not blocked
    allowed, _ = await check_login_rate(db_session, "ip-y", max_attempts=2)
    assert allowed
