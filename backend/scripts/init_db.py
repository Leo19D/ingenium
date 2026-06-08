"""Bootstrap baze za produkciju (Supabase/Postgres) — idempotentno.

Pokreće se jednom pri deployu (i sigurno pri svakom restartu):
  1. create_all — kreira sve tablice iz modela (izvor istine, uvijek aktualan).
  2. Osigura demo organizaciju (registracija/login dodjeljuje korisnike njoj).
  3. Osigura admin korisnika (owner) da se odmah možeš prijaviti.
  4. alembic stamp head — označi shemu kao migriranu (da buduće migracije rade).

Pokretanje: `python -m scripts.init_db`
Env: ADMIN_EMAIL (default leodupanovic1@gmail.com), ADMIN_PASSWORD (obavezno
za kreiranje admina; ako nije postavljen, admin se preskače i registrira se
kroz app).
"""

from __future__ import annotations

import asyncio
import os
import uuid

from sqlalchemy import select

from app.core.security import hash_password
from app.db.base import Base
from app.db.models.organization import Organization
from app.db.models.user import Membership, User
from app.db.session import AsyncSessionFactory, engine

DEMO_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def _ensure_org(db) -> None:
    org = await db.get(Organization, DEMO_ORG_ID)
    if org:
        return
    db.add(Organization(
        id=DEMO_ORG_ID, name="Ingenium Trade d.o.o.", slug="ingenium",
        country_code="HR", base_currency="EUR", locale="hr", timezone="Europe/Zagreb",
    ))
    await db.commit()
    print("✓ demo organizacija kreirana")


async def _ensure_admin(db) -> None:
    email = os.getenv("ADMIN_EMAIL", "leodupanovic1@gmail.com").lower().strip()
    password = os.getenv("ADMIN_PASSWORD")
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        return
    if not password:
        print(f"⚠ ADMIN_PASSWORD nije postavljen — admin '{email}' se ne kreira "
              f"(registriraj se kroz app).")
        return
    user = User(
        id=uuid.uuid4(), email=email, full_name="Leo Dupanovic",
        auth_provider="local", hashed_password=hash_password(password),
        locale="hr", is_active=True, is_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(Membership(org_id=DEMO_ORG_ID, user_id=user.id, role="owner"))
    await db.commit()
    print(f"✓ admin korisnik '{email}' (owner) kreiran")


def _stamp_head() -> None:
    try:
        from alembic.config import Config

        from alembic import command
        cfg = Config("alembic.ini")
        command.stamp(cfg, "head")
        print("✓ alembic stamp head")
    except Exception as e:
        print(f"⚠ alembic stamp preskočen: {e}")


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ create_all (sve tablice)")
    async with AsyncSessionFactory() as db:
        await _ensure_org(db)
        await _ensure_admin(db)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
    _stamp_head()  # izvan async petlje (alembic env je async)
    print("✅ baza spremna")
