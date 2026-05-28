"""Document processing tasks: OCR, parsing, extraction."""

from __future__ import annotations

import uuid

import structlog

from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, name="documents.process", max_retries=3)
def process_document(self, document_id: str) -> dict:  # type: ignore[no-untyped-def]
    """
    End-to-end pipeline for a single uploaded document.

    Steps (each in its own helper, TODO implement):
      1. Load document from S3
      2. Detect type, language
      3. Route to appropriate parser (pdfplumber, Azure DI, etc.)
      4. Run LLM-assisted line item extraction
      5. Score confidence, persist DocumentExtraction
      6. Enqueue catalog matching task if confidence high enough
    """
    logger.info("process_document_started", document_id=document_id, task_id=self.request.id)
    # TODO: implement pipeline
    return {"document_id": document_id, "status": "TODO"}
