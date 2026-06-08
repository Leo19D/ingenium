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

    Preferira Resend (HTTP) ako je RESEND_API_KEY postavljen — cloud hostovi
    blokiraju SMTP. Inače SMTP. Tiho preskače ako ništa nije konfigurirano.
    """
    if settings.RESEND_API_KEY:
        await _send_resend(to, subject, html, attachment, attachment_name, attachment_mime)
        return
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("email_not_configured — nije poslano", extra={"to": to})
        return
    await asyncio.to_thread(
        _send_sync, to, subject, html, attachment, attachment_name, attachment_mime
    )


async def _send_resend(
    to: str, subject: str, html: str,
    attachment: bytes | None, attachment_name: str | None, attachment_mime: str,
) -> None:
    """Pošalji preko Resend HTTP API-ja (port 443, ne blokira ga cloud host)."""
    import base64

    import httpx

    payload: dict = {
        "from": settings.RESEND_FROM,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if attachment is not None:
        payload["attachments"] = [{
            "filename": attachment_name or "prilog.pdf",
            "content": base64.b64encode(attachment).decode(),
        }]
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json=payload,
        )
    if r.status_code >= 300:
        logger.error("resend_send_failed status=%s body=%s", r.status_code, r.text[:300])
        raise RuntimeError(f"Resend greška {r.status_code}: {r.text[:200]}")


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
