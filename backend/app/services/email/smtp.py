"""Async email sender via Gmail SMTP (STARTTLS, port 587)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, html: str) -> None:
    """Send an HTML email. Raises if SMTP is configured but sending fails."""
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("smtp_not_configured — email not sent", extra={"to": to})
        return
    await asyncio.to_thread(_send_sync, to, subject, html)


def _send_sync(to: str, subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.sendmail(settings.SMTP_FROM, [to], msg.as_string())

    logger.info("email_sent", extra={"to": to, "subject": subject})
