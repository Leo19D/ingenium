"""Email and notification tasks."""

from __future__ import annotations

import structlog

from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="notifications.send_email")
def send_email(to: str, subject: str, body_html: str) -> None:
    """Send a transactional email."""
    logger.info("send_email", to=to, subject=subject)
    # TODO: integrate with SMTP/SendGrid/Postmark
