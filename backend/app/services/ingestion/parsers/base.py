"""Base parser interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ParsedTable:
    rows: list[list[str]]
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # (x0, y0, x1, y1)


@dataclass
class ParsedDocument:
    raw_text: str
    tables: list[ParsedTable]
    detected_lang: str | None = None
    metadata: dict | None = None


class DocumentParser(ABC):
    """Parse a binary document into raw text + tables."""

    @abstractmethod
    async def parse(self, file_bytes: bytes, filename: str) -> ParsedDocument: ...
