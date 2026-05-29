"""Unit testovi za security.py — JWT i bcrypt."""

from __future__ import annotations

import pytest
from jose import JWTError

from app.core.security import (
    _RateLimiter,
    _TokenBlacklist,
    blacklist_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_verification_token,
    hash_password,
    is_token_blacklisted,
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


@pytest.mark.unit
def test_token_blacklist_add_and_check():
    bl = _TokenBlacklist()
    bl.add("tok-abc")
    assert bl.contains("tok-abc")
    assert not bl.contains("tok-xyz")


@pytest.mark.unit
def test_token_blacklist_global():
    token = create_access_token("u1", "o1")
    assert not is_token_blacklisted(token)
    blacklist_token(token)
    assert is_token_blacklisted(token)


@pytest.mark.unit
def test_rate_limiter_allows_under_limit():
    rl = _RateLimiter(max_attempts=3, window_seconds=60)
    assert rl.is_allowed("ip-test-a")
    assert rl.is_allowed("ip-test-a")
    assert rl.is_allowed("ip-test-a")


@pytest.mark.unit
def test_rate_limiter_blocks_over_limit():
    rl = _RateLimiter(max_attempts=3, window_seconds=60)
    rl.is_allowed("ip-test-b")
    rl.is_allowed("ip-test-b")
    rl.is_allowed("ip-test-b")
    assert not rl.is_allowed("ip-test-b")


@pytest.mark.unit
def test_rate_limiter_independent_keys():
    rl = _RateLimiter(max_attempts=2, window_seconds=60)
    rl.is_allowed("ip-x")
    rl.is_allowed("ip-x")
    assert not rl.is_allowed("ip-x")
    assert rl.is_allowed("ip-y")
