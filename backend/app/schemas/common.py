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
