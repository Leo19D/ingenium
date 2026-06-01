"""
Discrete login security alerts.

Sends a detailed notification to the admin (ingeniumtrade@gmail.com) on every
successful login: WHO logged in, WHEN, WHERE (geo from IP), and HOW (browser/OS).

The user logging in is never notified and never sees that this alert exists.
Failures here never block or affect the login flow.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

import httpx

from app.services.email.smtp import send_email

logger = logging.getLogger(__name__)

# Tko prima alerte — admini. Korisnik koji se logira ovo nikad ne vidi.
ADMIN_ALERT_EMAILS = ["leodupanovic1@gmail.com"]

_PRIVATE_IP_PREFIXES = ("10.", "192.168.", "172.16.", "172.17.", "172.18.",
                        "172.19.", "172.2", "172.30.", "172.31.", "127.", "::1")


# --------------------------------------------------------------------------- #
# IP geolocation                                                              #
# --------------------------------------------------------------------------- #

async def _geolocate(ip: str) -> dict:
    """Resolve IP → city/country/ISP. Returns {} on failure or private IP."""
    if not ip or ip == "unknown" or ip.startswith(_PRIVATE_IP_PREFIXES):
        return {"local": True}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,country,regionName,city,isp,proxy,hosting,query"},
            )
            data = r.json()
            if data.get("status") == "success":
                return data
    except Exception as e:
        logger.warning("geolocation_failed", extra={"ip": ip, "error": str(e)})
    return {}


# --------------------------------------------------------------------------- #
# User-agent parsing (lightweight, no extra deps)                             #
# --------------------------------------------------------------------------- #

def _parse_user_agent(ua: str) -> dict:
    """Extract browser, OS, device type from a user-agent string."""
    if not ua:
        return {"browser": "Nepoznato", "os": "Nepoznato", "device": "Nepoznato"}

    ua_l = ua.lower()

    # OS — iPhone/iPad PRIJE macOS jer njihov UA sadrži "like Mac OS X"
    if "iphone" in ua_l or "ipad" in ua_l:
        m = re.search(r"os (\d+[._]\d+)", ua_l)
        ver = m.group(1).replace("_", ".") if m else ""
        os_name = f"iOS {ver}".strip()
    elif "android" in ua_l:
        m = re.search(r"android (\d+)", ua_l)
        os_name = f"Android {m.group(1)}" if m else "Android"
    elif "windows nt 10" in ua_l:
        os_name = "Windows 10/11"
    elif "windows" in ua_l:
        os_name = "Windows"
    elif "mac os x" in ua_l or "macintosh" in ua_l:
        m = re.search(r"mac os x (\d+[._]\d+)", ua_l)
        ver = m.group(1).replace("_", ".") if m else ""
        os_name = f"macOS {ver}".strip()
    elif "linux" in ua_l:
        os_name = "Linux"
    else:
        os_name = "Nepoznato"

    # Browser (order matters — Edge/Chrome both contain "chrome")
    if "edg/" in ua_l or "edge" in ua_l:
        browser = "Microsoft Edge"
    elif "opr/" in ua_l or "opera" in ua_l:
        browser = "Opera"
    elif "firefox" in ua_l:
        browser = "Firefox"
    elif "chrome" in ua_l and "safari" in ua_l:
        browser = "Chrome"
    elif "safari" in ua_l:
        browser = "Safari"
    else:
        browser = "Nepoznato"

    # Device
    if "iphone" in ua_l:
        device = "iPhone"
    elif "ipad" in ua_l:
        device = "iPad"
    elif "android" in ua_l and "mobile" in ua_l:
        device = "Android telefon"
    elif "android" in ua_l:
        device = "Android tablet"
    elif "mobile" in ua_l:
        device = "Mobitel"
    else:
        device = "Računalo"

    return {"browser": browser, "os": os_name, "device": device}


# --------------------------------------------------------------------------- #
# Public entrypoint                                                           #
# --------------------------------------------------------------------------- #

async def send_login_alert(
    *,
    email: str,
    full_name: str,
    ip: str,
    user_agent: str,
) -> None:
    """
    Fire-and-forget login alert to admin. Never raises.
    Call this AFTER a successful login (OTP verified).
    """
    try:
        geo = await _geolocate(ip)
        ua = _parse_user_agent(user_agent)
        now = datetime.now(UTC)

        # Lokacija string
        if geo.get("local"):
            location = "Lokalna mreža (development)"
        elif geo.get("city"):
            location = f"{geo['city']}, {geo.get('regionName', '')}, {geo.get('country', '')}".strip(", ")
        elif geo.get("country"):
            location = geo["country"]
        else:
            location = "Nepoznata lokacija"

        isp = geo.get("isp", "—")
        # Sumnjive zastavice
        flags = []
        if geo.get("proxy"):
            flags.append("VPN/Proxy")
        if geo.get("hosting"):
            flags.append("Data centar / hosting")

        html = _alert_html(
            full_name=full_name,
            email=email,
            ip=ip,
            location=location,
            isp=isp,
            browser=ua["browser"],
            os=ua["os"],
            device=ua["device"],
            timestamp=now.strftime("%d.%m.%Y. u %H:%M:%S UTC"),
            flags=flags,
        )

        # Anti-spam: ne šalji alert osobi koja se upravo prijavila —
        # ona zna da se prijavila i već je dobila OTP kod.
        recipients = [a for a in ADMIN_ALERT_EMAILS if a.lower() != email.lower()]
        if not recipients:
            logger.info("login_alert_skipped_self", extra={"email": email})
            return

        subject = f"🔓 Prijava — {full_name} ({email})"
        for admin in recipients:
            try:
                await send_email(to=admin, subject=subject, html=html)
            except Exception as e:
                logger.warning("login_alert_recipient_failed",
                               extra={"recipient": admin, "error": str(e)})
        logger.info("login_alert_sent",
                    extra={"email": email, "ip": ip, "recipients": len(recipients)})
    except Exception as e:
        logger.warning("login_alert_failed", extra={"email": email, "error": str(e)})


def _alert_html(
    *,
    full_name: str,
    email: str,
    ip: str,
    location: str,
    isp: str,
    browser: str,
    os: str,
    device: str,
    timestamp: str,
    flags: list[str],
) -> str:
    flag_block = ""
    if flags:
        flag_items = " · ".join(flags)
        flag_block = f"""
        <tr>
          <td style="padding:14px 18px;background:#1a0e0a;border:1px solid #3a2218;
                      border-left:3px solid #f47a6a;border-radius:0 10px 10px 0;">
            <p style="margin:0;font-family:Arial,sans-serif;font-size:12.5px;color:#d89080;line-height:1.6;">
              <strong style="color:#f4a08a;">⚠ Pažnja:</strong> {flag_items} detektiran.
              Provjerite je li ova prijava očekivana.
            </p>
          </td>
        </tr>
        <tr><td style="height:14px;"></td></tr>"""

    def row(label: str, value: str, mono: bool = False) -> str:
        fam = "Courier New,monospace" if mono else "Arial,sans-serif"
        return f"""
        <tr>
          <td style="padding:11px 0;border-bottom:1px solid #1a2019;width:40%;
                      font-family:Arial,sans-serif;font-size:11px;font-weight:600;
                      letter-spacing:0.06em;text-transform:uppercase;color:#5a7a60;
                      vertical-align:top;">{label}</td>
          <td style="padding:11px 0;border-bottom:1px solid #1a2019;
                      font-family:{fam};font-size:13.5px;color:#ddeadf;
                      font-weight:600;">{value}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="hr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#060908;">
<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#060908">
<tr><td align="center" style="padding:48px 16px 64px;">
  <table width="500" cellpadding="0" cellspacing="0" style="max-width:500px;">

    <!-- Logo -->
    <tr><td style="padding-bottom:24px;">
      <table cellpadding="0" cellspacing="0"><tr valign="middle">
        <td width="34" height="34" bgcolor="#a8f4b8" align="center"
            style="border-radius:9px;font-size:17px;line-height:34px;">⚡</td>
        <td style="padding-left:10px;font-family:Arial,sans-serif;font-size:16px;
                    font-weight:700;color:#c8e8ca;">Ingenium</td>
        <td style="padding-left:10px;">
          <span style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;
                        letter-spacing:0.08em;text-transform:uppercase;color:#a8f4b8;
                        background:rgba(168,244,184,0.08);border:1px solid rgba(168,244,184,0.2);
                        border-radius:20px;padding:3px 9px;">Security</span>
        </td>
      </tr></table>
    </td></tr>

    <!-- Card -->
    <tr><td bgcolor="#0c1410" style="border-radius:18px;border:1px solid #1c2a1e;overflow:hidden;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr><td bgcolor="#a8f4b8" height="3" style="font-size:0;line-height:0;">&nbsp;</td></tr>
      </table>

      <table width="100%" cellpadding="0" cellspacing="0"><tr><td style="padding:36px 40px 32px;">

        <p style="margin:0 0 6px;font-family:Arial,sans-serif;font-size:11px;font-weight:700;
                    letter-spacing:0.12em;text-transform:uppercase;color:#4a7a52;">Uspješna prijava</p>
        <h1 style="margin:0 0 8px;font-family:Arial,sans-serif;font-size:22px;font-weight:800;
                    color:#ddeadf;letter-spacing:-0.5px;">{full_name}</h1>
        <p style="margin:0 0 28px;font-family:Courier New,monospace;font-size:13px;color:#7a9480;">{email}</p>

        {flag_block}

        <table width="100%" cellpadding="0" cellspacing="0">
          {row("Vrijeme", timestamp, mono=True)}
          {row("Lokacija", location)}
          {row("IP adresa", ip, mono=True)}
          {row("Mreža / ISP", isp)}
          {row("Uređaj", device)}
          {row("Operativni sustav", os)}
          {row("Preglednik", browser)}
        </table>

      </td></tr></table>
    </td></tr>

    <!-- Footer -->
    <tr><td style="padding:20px 4px 0;">
      <p style="margin:0;font-family:Arial,sans-serif;font-size:11px;color:#2a3c2c;line-height:1.6;">
        Automatski sigurnosni izvještaj · Ingenium · Šalje se pri svakoj prijavi
      </p>
    </td></tr>

  </table>
</td></tr>
</table>
</body>
</html>"""
