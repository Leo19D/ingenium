"""LLM-related background tasks (catalog matching, summarization, etc.)."""

from __future__ import annotations

import structlog

from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, name="llm.match_catalog", max_retries=2)
def match_catalog_items(self, document_id: str) -> dict:  # type: ignore[no-untyped-def]
    """Run catalog matching for all line items of a document."""
    logger.info("match_catalog_items", document_id=document_id)
    # TODO: implement
    return {"document_id": document_id, "status": "TODO"}
