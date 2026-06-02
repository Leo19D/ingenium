"""
Audit logging — append-only trag tko je što radio.

log_action() je fire-and-forget: nikad ne ruši glavnu operaciju.
Bilježi kritične akcije: quote lifecycle, login, create/delete entiteta.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit import AuditLog

logger = logging.getLogger(__name__)


async def log_action(
    db: AsyncSession,
    *,
    org_id: UUID,
    action: str,
    user_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    commit: bool = True,
) -> None:
    """
    Upiši audit zapis. Greške se gutaju (audit ne smije srušiti akciju).

    action: 'quote.created', 'quote.sent', 'quote.approved', 'quote.outcome',
            'client.created', 'auth.login', 'document.uploaded', ...
    commit: ako je False, pretpostavlja da pozivatelj commita (dio veće transakcije)
    """
    entry = AuditLog(
        org_id=org_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    # Savepoint izolacija: ako audit insert padne, rollback SAMO savepointa —
    # glavna transakcija (već commitana promjena) ostaje netaknuta.
    try:
        async with db.begin_nested():
            db.add(entry)
        if commit:
            await db.commit()
    except Exception as e:
        logger.warning("audit_log_failed", extra={"action": action, "error": str(e)})
