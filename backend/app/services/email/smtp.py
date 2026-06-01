"""Async email sender via Gmail SMTP (STARTTLS, port 587)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


async def send_email(
    to: str,
    subject: str,
    html: str,
    *,
    attachment: bytes | None = None,
    attachment_name: str | None = None,
    attachment_mime: str = "application/pdf",
) -> None:
    """Send an HTML email, optionally with one binary attachment.

    Raises if SMTP is configured but sending fails; silently skips if SMTP
    is not configured (dev without credentials).
    """
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("smtp_not_configured — email not sent", extra={"to": to})
        return
    await asyncio.to_thread(
        _send_sync, to, subject, html, attachment, attachment_name, attachment_mime
    )


def _send_sync(
    to: str,
    subject: str,
    html: str,
    attachment: bytes | None,
    attachment_name: str | None,
    attachment_mime: str,
) -> None:
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to

    body = MIMEMultipart("alternative")
    body.attach(MIMEText(html, "html", "utf-8"))
    msg.attach(body)

    if attachment is not None:
        subtype = attachment_mime.split("/", 1)[-1] if "/" in attachment_mime else "octet-stream"
        part = MIMEApplication(attachment, _subtype=subtype)
        part.add_header(
            "Content-Disposition", "attachment",
            filename=attachment_name or "prilog",
        )
        msg.attach(part)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.sendmail(settings.SMTP_FROM, [to], msg.as_string())

    logger.info("email_sent", extra={"to": to, "subject": subject,
                                     "has_attachment": attachment is not None})
