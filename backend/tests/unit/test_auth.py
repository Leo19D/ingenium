"""Integracijski testovi za auth endpointe (SQLite in-memory)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.user import Membership, User

DEMO_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def _seed_org(db: AsyncSession) -> None:
    from app.db.models.organization import Organization

    org = Organization(
        id=DEMO_ORG_ID,
        name="Test Org",
        slug="test-org",
        country_code="HR",
        base_currency="EUR",
        locale="hr-HR",
        timezone="Europe/Zagreb",
    )
    db.add(org)
    await db.commit()


async def _make_verified_user(db: AsyncSession, email: str, password: str) -> User:
    await _seed_org(db)
    user = User(
        email=email,
        full_name="Test User",
        auth_provider="local",
        hashed_password=hash_password(password),
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(Membership(org_id=DEMO_ORG_ID, user_id=user.id, role="owner"))
    await db.commit()
    return user


# --------------------------------------------------------------------------- #
# Email whitelist                                                               #
# --------------------------------------------------------------------------- #

@pytest.mark.unit
async def test_register_blocked_for_unknown_domain(client: AsyncClient, db_session: AsyncSession):
    await _seed_org(db_session)
    with patch("app.api.v1.auth.send_email", new_callable=AsyncMock):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "netko@gmail.com",
            "password": "lozinka123",
            "full_name": "Netko Tko",
        })
    assert resp.status_code == 403


@pytest.mark.unit
async def test_register_allowed_for_admin_email(client: AsyncClient, db_session: AsyncSession):
    await _seed_org(db_session)
    with patch("app.api.v1.auth.send_email", new_callable=AsyncMock) as mock_mail:
        resp = await client.post("/api/v1/auth/register", json={
            "email": "leodupanovic1@gmail.com",
            "password": "lozinka123",
            "full_name": "Leo Dupanovic",
        })
    assert resp.status_code == 201
    mock_mail.assert_called_once()


@pytest.mark.unit
async def test_register_allowed_for_ingeniumtrade(client: AsyncClient, db_session: AsyncSession):
    await _seed_org(db_session)
    with patch("app.api.v1.auth.send_email", new_callable=AsyncMock):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "marko@ingeniumtrade.hr",
            "password": "lozinka123",
            "full_name": "Marko Marković",
        })
    assert resp.status_code == 201


@pytest.mark.unit
async def test_register_duplicate_email(client: AsyncClient, db_session: AsyncSession):
    await _seed_org(db_session)
    payload = {"email": "marko@ingeniumtrade.hr", "password": "lozinka123", "full_name": "Marko"}
    with patch("app.api.v1.auth.send_email", new_callable=AsyncMock):
        await client.post("/api/v1/auth/register", json=payload)
        resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 409


@pytest.mark.unit
async def test_register_short_password(client: AsyncClient, db_session: AsyncSession):
    await _seed_org(db_session)
    with patch("app.api.v1.auth.send_email", new_callable=AsyncMock):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "marko@ingeniumtrade.hr",
            "password": "kratko",
            "full_name": "Marko",
        })
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Login                                                                        #
# --------------------------------------------------------------------------- #

@pytest.mark.unit
async def test_login_success(client: AsyncClient, db_session: AsyncSession):
    await _make_verified_user(db_session, "leo@ingeniumtrade.hr", "lozinka123")
    resp = await client.post("/api/v1/auth/login", json={
        "email": "leo@ingeniumtrade.hr",
        "password": "lozinka123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.unit
async def test_login_wrong_password(client: AsyncClient, db_session: AsyncSession):
    await _make_verified_user(db_session, "leo@ingeniumtrade.hr", "lozinka123")
    resp = await client.post("/api/v1/auth/login", json={
        "email": "leo@ingeniumtrade.hr",
        "password": "pogresna",
    })
    assert resp.status_code == 401


@pytest.mark.unit
async def test_login_unverified_user(client: AsyncClient, db_session: AsyncSession):
    await _seed_org(db_session)
    user = User(
        email="neverified@ingeniumtrade.hr",
        full_name="Test",
        auth_provider="local",
        hashed_password=hash_password("lozinka123"),
        is_active=True,
        is_verified=False,
    )
    db_session.add(user)
    await db_session.commit()

    resp = await client.post("/api/v1/auth/login", json={
        "email": "neverified@ingeniumtrade.hr",
        "password": "lozinka123",
    })
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# /me                                                                          #
# --------------------------------------------------------------------------- #

@pytest.mark.unit
async def test_me_with_valid_token(client: AsyncClient, db_session: AsyncSession):
    await _make_verified_user(db_session, "leo@ingeniumtrade.hr", "lozinka123")
    login = await client.post("/api/v1/auth/login", json={
        "email": "leo@ingeniumtrade.hr", "password": "lozinka123"
    })
    token = login.json()["access_token"]

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "leo@ingeniumtrade.hr"


@pytest.mark.unit
async def test_me_without_token(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Protected endpoints                                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.unit
async def test_clients_protected(client: AsyncClient):
    resp = await client.get("/api/v1/clients/")
    assert resp.status_code == 401


@pytest.mark.unit
async def test_suppliers_protected(client: AsyncClient):
    resp = await client.get("/api/v1/suppliers/")
    assert resp.status_code == 401


@pytest.mark.unit
async def test_stock_protected(client: AsyncClient):
    resp = await client.get("/api/v1/stock-items/")
    assert resp.status_code == 401


@pytest.mark.unit
async def test_clients_accessible_with_token(client: AsyncClient, db_session: AsyncSession):
    await _make_verified_user(db_session, "leo@ingeniumtrade.hr", "lozinka123")
    login = await client.post("/api/v1/auth/login", json={
        "email": "leo@ingeniumtrade.hr", "password": "lozinka123"
    })
    token = login.json()["access_token"]
    resp = await client.get("/api/v1/clients/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Refresh token                                                                #
# --------------------------------------------------------------------------- #

@pytest.mark.unit
async def test_refresh_token(client: AsyncClient, db_session: AsyncSession):
    await _make_verified_user(db_session, "leo@ingeniumtrade.hr", "lozinka123")
    login = await client.post("/api/v1/auth/login", json={
        "email": "leo@ingeniumtrade.hr", "password": "lozinka123"
    })
    refresh = login.json()["refresh_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.unit
async def test_refresh_with_access_token_fails(client: AsyncClient, db_session: AsyncSession):
    await _make_verified_user(db_session, "leo@ingeniumtrade.hr", "lozinka123")
    login = await client.post("/api/v1/auth/login", json={
        "email": "leo@ingeniumtrade.hr", "password": "lozinka123"
    })
    access = login.json()["access_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401
