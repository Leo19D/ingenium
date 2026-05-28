"""CSV document parser."""

from __future__ import annotations

from app.services.ingestion.parsers.base import DocumentParser, ParsedDocument


class CsvParser(DocumentParser):
    async def parse(self, file_bytes: bytes, filename: str) -> ParsedDocument:
        # TODO: implement using appropriate library
        raise NotImplementedError("CsvParser.parse not yet implemented")
