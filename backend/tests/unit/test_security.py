"""Unit testovi za security.py — JWT i bcrypt."""

from __future__ import annotations

import pytest
from jose import JWTError

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_verification_token,
    hash_password,
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
