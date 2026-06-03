"""In-process scheduler — automatske notifikacije bez Celery/brokera.

Solo-dev setup vrti čisti uvicorn (bez Dockera/Celery beata), pa periodičke
zadatke radimo asyncio background taskom pokrenutim u lifespanu. Trenutno:
podsjetnici za ponude koje uskoro ističu (status='sent', valid_until ≤ N dana).

Dedup: prije slanja provjeri postoji li audit zapis 'quote.reminder_sent' za tu
ponudu — tako podsjetnik ide najviše jednom po ponudi, čak i preko restarta.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import and_, exists, select

from app.config import settings
from app.db.models.audit import AuditLog
from app.db.models.organization import Organization
from app.db.models.quote import Quote
from app.db.models.user import Membership, User
from app.db.session import AsyncSessionFactory
from app.services.audit import log_action
from app.services.email.smtp import send_email

logger = logging.getLogger(__name__)

REMINDER_ACTION = "quote.reminder_sent"
EXPIRY_WINDOW_DAYS = 3          # podsjeti kad ostane ≤ 3 dana
CHECK_INTERVAL_SECONDS = 6 * 60 * 60  # provjeri svakih 6h


async def _org_recipient(db, org_id: UUID) -> tuple[str, str] | None:
    """Vrati (email, ime) vlasnika/admina org. None ako nema."""
    row = (await db.execute(
        select(User.email, User.full_name)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org_id, Membership.role.in_(("owner", "admin")))
        .order_by(Membership.role.desc())   # 'owner' > 'admin' abecedno → owner prvi
        .limit(1)
    )).first()
    return (row[0], row[1] or row[0]) if row else None


def _reminder_html(org_name: str, rows: list[dict]) -> str:
    lines = "".join(
        f'<tr><td style="padding:8px 12px;border-bottom:1px solid #ebedf0">Ponuda V{r["version"]}</td>'
        f'<td style="padding:8px 12px;border-bottom:1px solid #ebedf0;text-align:right">'
        f'€{r["total"]:,.2f}</td>'
        f'<td style="padding:8px 12px;border-bottom:1px solid #ebedf0;text-align:right;'
        f'color:{"#c23934" if r["days"] <= 1 else "#9a6700"}">{r["days"]} dan(a)</td></tr>'
        for r in rows
    )
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;margin:0 auto;color:#1a1d21">
  <div style="padding:20px 0;border-bottom:2px solid #2257b3">
    <span style="font-size:18px;font-weight:700">{org_name}</span>
    <span style="color:#62686f;font-size:13px"> · Podsjetnik</span>
  </div>
  <p style="font-size:14px;line-height:1.5;margin:20px 0 8px">
    Sljedeće poslane ponude uskoro ističu. Razmotrite follow-up s klijentom:
  </p>
  <table style="width:100%;border-collapse:collapse;font-size:13px;margin:12px 0">
    <thead><tr style="color:#62686f;text-align:left">
      <th style="padding:8px 12px;font-weight:600">Ponuda</th>
      <th style="padding:8px 12px;font-weight:600;text-align:right">Iznos</th>
      <th style="padding:8px 12px;font-weight:600;text-align:right">Ističe za</th>
    </tr></thead>
    <tbody>{lines}</tbody>
  </table>
  <p style="font-size:12px;color:#9aa0a8;margin-top:24px">
    Automatska obavijest — Ingenium AI Quote &amp; Procurement Platform.
  </p>
</div>"""


async def run_expiry_reminders() -> int:
    """Jedan prolaz: nađi ponude koje uskoro ističu i pošalji podsjetnik.

    Vraća broj ponuda za koje je podsjetnik poslan (korisno za testove).
    """
    today = date.today()
    cutoff = today + timedelta(days=EXPIRY_WINDOW_DAYS)
    sent_count = 0

    async with AsyncSessionFactory() as db:
        # Ponude koje ističu u prozoru i NEMAJU već poslan podsjetnik (dedup preko audita)
        already = (
            select(AuditLog.entity_id)
            .where(AuditLog.action == REMINDER_ACTION, AuditLog.entity_id == Quote.id)
        )
        rows = (await db.execute(
            select(Quote.id, Quote.org_id, Quote.version, Quote.total, Quote.valid_until)
            .where(
                and_(
                    Quote.status == "sent",
                    Quote.valid_until.is_not(None),
                    Quote.valid_until >= today,
                    Quote.valid_until <= cutoff,
                    ~exists(already),
                )
            )
        )).all()

        if not rows:
            return 0

        # Grupiraj po org da pošaljemo jedan email po organizaciji
        by_org: dict[UUID, list[dict]] = {}
        for qid, org_id, ver, total, valid_until in rows:
            by_org.setdefault(org_id, []).append({
                "id": qid, "version": ver, "total": float(total or 0),
                "days": (valid_until - today).days,
            })

        for org_id, items in by_org.items():
            recipient = await _org_recipient(db, org_id)
            if not recipient:
                logger.warning("expiry_reminder_no_recipient org=%s", org_id)
                continue
            org = await db.get(Organization, org_id)
            org_name = org.name if org else "Ingenium"
            email, _name = recipient
            items.sort(key=lambda x: x["days"])
            try:
                await send_email(
                    to=email,
                    subject=f"Podsjetnik: {len(items)} ponuda uskoro ističe",
                    html=_reminder_html(org_name, items),
                )
            except Exception:
                logger.exception("expiry_reminder_send_failed org=%s", org_id)
                continue
            # Zabilježi u audit da ne šaljemo opet
            for it in items:
                await log_action(
                    db, org_id=org_id, action=REMINDER_ACTION,
                    entity_type="quote", entity_id=it["id"],
                    after_state={"days_left": it["days"]}, commit=False,
                )
                sent_count += 1
            await db.commit()

    logger.info("expiry_reminders_done sent=%d", sent_count)
    return sent_count


async def scheduler_loop() -> None:
    """Beskonačna petlja — pokreni periodičke zadatke. Pokreće se u lifespanu."""
    logger.info("scheduler_started interval=%ds", CHECK_INTERVAL_SECONDS)
    while True:
        try:
            await run_expiry_reminders()
        except asyncio.CancelledError:
            logger.info("scheduler_cancelled")
            raise
        except Exception:
            logger.exception("scheduler_pass_failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def should_run_scheduler() -> bool:
    """Ne diži scheduler u testovima (SQLite in-memory) ni bez SMTP-a."""
    return (
        settings.ENABLE_SCHEDULER
        and "memory" not in settings.DATABASE_URL
        and bool(settings.SMTP_HOST)
    )
