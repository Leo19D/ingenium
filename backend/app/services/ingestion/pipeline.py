"""
Document ingestion pipeline orchestrator.

Pipeline:
    upload → classify → parse → extract → score → store → enqueue match
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


class IngestionPipeline:
    """Coordinates document processing from upload to structured output."""

    async def process(self, document_id: str) -> None:
        """Run the full pipeline for one document. Idempotent."""
        logger.info("ingestion_pipeline_start", document_id=document_id)
        # TODO:
        # 1. Load Document row + S3 object
        # 2. Detect mime/lang/type
        # 3. Pick parser via parsers.dispatch()
        # 4. Run parser → raw text/tables
        # 5. Run LLM structured extractor
        # 6. Score confidence per item + overall
        # 7. Persist DocumentExtraction
        # 8. If high confidence → enqueue catalog matching
        # 9. Else → flag needs_review
