"""Integration: in-process scheduler — podsjetnici za isteke ponuda + dedup."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.organization import Organization
from app.db.models.project import Project
from app.db.models.quote import Quote
from app.db.models.user import Membership, User

ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
PROJ_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")


@pytest_asyncio.fixture
async def factory(db_engine):
    f = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with f() as s:
        s.add_all([
            Organization(id=ORG_ID, name="Ingenium", slug="ingenium",
                         country_code="HR", base_currency="EUR"),
            User(id=USER_ID, email="owner@ingeniumtrade.hr", full_name="Owner",
                 is_active=True, is_verified=True),
            Membership(org_id=ORG_ID, user_id=USER_ID, role="owner"),
            Project(id=PROJ_ID, org_id=ORG_ID, name="Hotel", status="quoting"),
            # Ponuda istječe za 2 dana → unutar prozora od 3 dana
            Quote(id=uuid.uuid4(), org_id=ORG_ID, project_id=PROJ_ID, version=1,
                  status="sent", currency="EUR", total=1000,
                  valid_until=date.today() + timedelta(days=2)),
            # Ova ne smije okinuti — istječe za 10 dana
            Quote(id=uuid.uuid4(), org_id=ORG_ID, project_id=PROJ_ID, version=2,
                  status="sent", currency="EUR", total=500,
                  valid_until=date.today() + timedelta(days=10)),
        ])
        await s.commit()
    return f


@pytest.mark.asyncio
async def test_expiry_reminder_sends_once_and_dedups(factory, monkeypatch):
    import app.services.scheduler as sched

    captured: list[dict] = []

    async def fake_send(*, to, subject, html, **kw):
        captured.append({"to": to, "subject": subject})

    monkeypatch.setattr(sched, "AsyncSessionFactory", factory)
    monkeypatch.setattr(sched, "send_email", fake_send)

    # Prvi prolaz — šalje za 1 ponudu (samo ona unutar prozora)
    n1 = await sched.run_expiry_reminders()
    assert n1 == 1, captured
    assert len(captured) == 1
    assert captured[0]["to"] == "owner@ingeniumtrade.hr"
    assert "1 ponuda" in captured[0]["subject"]

    # Drugi prolaz — dedup preko audita, ništa novo
    n2 = await sched.run_expiry_reminders()
    assert n2 == 0
    assert len(captured) == 1
