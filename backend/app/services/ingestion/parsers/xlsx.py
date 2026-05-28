"""XLSX document parser."""

from __future__ import annotations

from app.services.ingestion.parsers.base import DocumentParser, ParsedDocument


class XlsxParser(DocumentParser):
    async def parse(self, file_bytes: bytes, filename: str) -> ParsedDocument:
        # TODO: implement using appropriate library
        raise NotImplementedError("XlsxParser.parse not yet implemented")
