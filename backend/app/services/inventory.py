"""Inventory servis — jedinstveno mjesto za promjenu zalihe + revizijski trag.

Svaka promjena `quantity_on_hand` ide kroz `apply_movement`, koja ujedno
zapiše StockMovement. Tako je stanje skladišta uvijek objašnjivo.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.procurement import StockMovement
from app.db.models.stock import StockItem


async def apply_movement(
    db: AsyncSession,
    *,
    org_id: UUID,
    stock_item_id: UUID,
    delta: Decimal,
    reason: str,
    ref_type: str | None = None,
    ref_id: UUID | None = None,
    note: str | None = None,
) -> StockItem | None:
    """Promijeni zalihu za `delta` (+ulaz/−izlaz) i zabilježi kretanje.

    Ne dopušta da padne ispod 0 (clamp na 0). Vraća ažuriranu stavku ili None
    ako stavka ne pripada org (ignorira se).
    """
    item = await db.get(StockItem, stock_item_id)
    if not item or item.org_id != org_id:
        return None

    current = item.quantity_on_hand or Decimal("0")
    new_qty = current + delta
    if new_qty < 0:
        new_qty = Decimal("0")
    item.quantity_on_hand = new_qty
    if delta > 0:
        item.last_received_at = datetime.now(UTC)

    db.add(StockMovement(
        org_id=org_id,
        stock_item_id=stock_item_id,
        delta=delta,
        reason=reason,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    ))
    return item
