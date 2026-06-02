"""Common Pydantic schemas shared across resources."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """Base for response models that mirror ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class TimestampedSchema(ORMModel):
    id: UUID
    created_at: datetime
    updated_at: datetime


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int = 1
    page_size: int = 50
    pages: int = 1


async def paginate(
    db,
    base_query,
    *,
    page: int = 1,
    page_size: int = 50,
    search: str | None = None,
    search_columns: list | None = None,
    order_by=None,
) -> dict:
    """
    Generička paginacija + opcionalna server-side pretraga.

    base_query: SQLAlchemy select() već filtriran po org_id
    search_columns: lista kolona po kojima se traži (ILIKE) ako je search zadan
    Vraća dict spreman za PaginatedResponse.
    """
    from sqlalchemy import func, or_, select

    page = max(1, page)
    page_size = max(1, min(page_size, 200))

    q = base_query
    if search and search_columns:
        term = f"%{search.strip()}%"
        q = q.where(or_(*[col.ilike(term) for col in search_columns]))

    # Ukupan broj (count nad istim filterom)
    count_q = select(func.count()).select_from(q.order_by(None).subquery())
    total = (await db.execute(count_q)).scalar() or 0

    if order_by is not None:
        q = q.order_by(order_by)

    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = list((await db.execute(q)).scalars().all())

    pages = max(1, (total + page_size - 1) // page_size)
    return {"items": rows, "total": total, "page": page, "page_size": page_size, "pages": pages}
