"""Auth endpoints — register, verify-email, login, refresh, me."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, oauth2_scheme
from app.config import settings
from app.core.security import (
    OTP_EXPIRE_SECONDS,
    OTP_MAX_ATTEMPTS,
    blacklist_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_otp,
    generate_verification_token,
    hash_otp,
    hash_password,
    login_rate_limiter,
    validate_password_strength,
    verify_otp_hash,
    verify_password,
)
from app.db.models.user import Membership, User
from app.db.session import get_db
from app.services.email.smtp import send_email
from app.services.security_alert import send_login_alert

router = APIRouter()

# Jedini dopušteni pristup
_ADMIN_EMAIL = "leodupanovic1@gmail.com"
_ALLOWED_DOMAIN = "ingeniumtrade.hr"
_DEMO_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_VERIFY_TOKEN_HOURS = 24


def _is_allowed(email: str) -> bool:
    e = email.lower().strip()
    return e == _ADMIN_EMAIL or e.endswith(f"@{_ALLOWED_DOMAIN}")


# --------------------------------------------------------------------------- #
# Schemas                                                                      #
# --------------------------------------------------------------------------- #

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class OtpVerifyRequest(BaseModel):
    email: EmailStr
    code: str


class LoginStep1Response(BaseModel):
    step: str = "otp"
    message: str
    expires_in_seconds: int = OTP_EXPIRE_SECONDS


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_verified: bool


# --------------------------------------------------------------------------- #
# Endpoints                                                                    #
# --------------------------------------------------------------------------- #

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Registracija novog korisnika.
    Dopušteno: leodupanovic1@gmail.com i *@ingeniumtrade.hr
    Šalje verifikacijski email — bez potvrde nije moguća prijava.
    """
    email = req.email.lower().strip()

    if not _is_allowed(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registracija nije dozvoljena za ovu email adresu.",
        )

    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Korisnik s tom email adresom već postoji.",
        )

    pw_err = validate_password_strength(req.password)
    if pw_err:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=pw_err)

    token = generate_verification_token()
    expires = datetime.now(UTC) + timedelta(hours=_VERIFY_TOKEN_HOURS)

    user = User(
        email=email,
        full_name=req.full_name.strip(),
        auth_provider="local",
        hashed_password=hash_password(req.password),
        is_active=True,
        is_verified=False,
        verification_token=token,
        verification_token_expires_at=expires,
    )
    db.add(user)
    await db.flush()

    db.add(Membership(org_id=_DEMO_ORG_ID, user_id=user.id, role="sales"))
    await db.commit()

    verify_url = f"{settings.APP_BASE_URL}/api/v1/auth/verify-email?token={token}"
    await send_email(
        to=email,
        subject="Potvrdi email adresu — Ingenium",
        html=_verification_html(req.full_name.strip(), verify_url),
    )

    return {"message": "Registracija uspješna. Provjeri inbox i potvrdi email adresu."}


@router.get("/verify-email")
async def verify_email(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Klikni link iz emaila → aktivira račun → preusmjerava na login."""
    user = await db.scalar(
        select(User).where(User.verification_token == token)
    )

    if not user:
        return RedirectResponse(
            url=f"{settings.APP_BASE_URL}/?verify_error=invalid", status_code=302
        )

    if (
        user.verification_token_expires_at
        and user.verification_token_expires_at.replace(tzinfo=UTC)
        < datetime.now(UTC)
    ):
        return RedirectResponse(
            url=f"{settings.APP_BASE_URL}/?verify_error=expired", status_code=302
        )

    user.is_verified = True
    user.verification_token = None
    user.verification_token_expires_at = None
    await db.commit()

    return RedirectResponse(url=f"{settings.APP_BASE_URL}/?verified=1", status_code=302)


@router.post("/login")
async def login(
    request: Request,
    req: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginStep1Response:
    """Korak 1: validacija lozinke → šalje OTP kod na email."""
    client_ip = request.client.host if request.client else "unknown"

    if not login_rate_limiter.is_allowed(client_ip):
        wait = login_rate_limiter.seconds_until_reset(client_ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Previše neuspješnih pokušaja. Pokušaj ponovo za {wait} sekundi.",
            headers={"Retry-After": str(wait)},
        )

    email = req.email.lower().strip()
    user = await db.scalar(select(User).where(User.email == email))

    # Isti error za nepostojeći user i krivu lozinku — sprečava user enumeration
    if not user or not user.hashed_password or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Neispravni podaci za prijavu.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email adresa nije potvrđena. Provjeri inbox.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Korisnički račun je deaktiviran.",
        )

    # Generiraj OTP, invalidira prethodni
    otp = generate_otp()
    user.otp_hash = hash_otp(otp)
    user.otp_expires_at = datetime.now(UTC) + timedelta(seconds=OTP_EXPIRE_SECONDS)
    user.otp_attempts = 0
    await db.commit()

    import logging as _logging
    _log = _logging.getLogger(__name__)

    try:
        await send_email(
            to=email,
            subject="Vaš kod za prijavu — Ingenium",
            html=_otp_html(user.full_name, otp, OTP_EXPIRE_SECONDS),
        )
    except Exception as exc:
        _log.error("otp_email_send_failed", extra={"email": email, "error": str(exc)})
        if settings.ENV == "development":
            _log.warning(f"[DEV] OTP za {email}: {otp}")
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Nije moguće poslati kod. Pokušajte ponovo za koji trenutak.",
            )

    if settings.ENV == "development":
        _log.warning(f"[DEV] OTP za {email}: {otp}")

    # Otkrivamo samo dio emaila (npr. l***@gmail.com)
    parts = email.split("@")
    masked = parts[0][0] + "***@" + parts[1]
    return LoginStep1Response(
        message=f"Kod je poslan na {masked}",
        expires_in_seconds=OTP_EXPIRE_SECONDS,
    )


@router.post("/verify-otp")
async def verify_otp(
    request: Request,
    req: OtpVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Korak 2: validacija OTP koda → vraća JWT tokene."""
    client_ip = request.client.host if request.client else "unknown"

    if not login_rate_limiter.is_allowed(client_ip):
        wait = login_rate_limiter.seconds_until_reset(client_ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Previše pokušaja. Pokušaj ponovo za {wait} sekundi.",
            headers={"Retry-After": str(wait)},
        )

    email = req.email.lower().strip()
    user = await db.scalar(select(User).where(User.email == email))

    invalid_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Neispravan ili istekao kod.",
    )

    if not user or not user.otp_hash or not user.otp_expires_at:
        raise invalid_exc

    if user.otp_expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        user.otp_hash = None
        user.otp_expires_at = None
        user.otp_attempts = 0
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kod je istekao. Prijavite se ponovo.",
        )

    if user.otp_attempts >= OTP_MAX_ATTEMPTS:
        user.otp_hash = None
        user.otp_expires_at = None
        user.otp_attempts = 0
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Previše neispravnih pokušaja. Prijavite se ponovo.",
        )

    if not verify_otp_hash(req.code.strip(), user.otp_hash):
        user.otp_attempts += 1
        remaining = OTP_MAX_ATTEMPTS - user.otp_attempts
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Neispravan kod. Još {remaining} pokušaj(a).",
        )

    # OTP ispravan — čisti ga i vraća tokene
    user.otp_hash = None
    user.otp_expires_at = None
    user.otp_attempts = 0
    await db.commit()

    # Diskretni security alert administratoru — tko/kad/odakle/kako.
    # Fire-and-forget: nikad ne blokira prijavu, korisnik ne zna za ovo.
    await send_login_alert(
        email=email,
        full_name=user.full_name,
        ip=client_ip,
        user_agent=request.headers.get("user-agent", ""),
    )

    membership = await db.scalar(
        select(Membership).where(Membership.user_id == user.id).limit(1)
    )
    org_id = str(membership.org_id) if membership else str(_DEMO_ORG_ID)

    return TokenResponse(
        access_token=create_access_token(str(user.id), org_id),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh")
async def refresh_token(
    req: RefreshRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    """Obnovi access token koristeći refresh token."""
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Neispravan ili istekao refresh token.",
    )
    try:
        payload = decode_token(req.refresh_token)
    except JWTError:
        raise invalid

    if payload.get("type") != "refresh":
        raise invalid

    user_id = payload.get("sub")
    if not user_id:
        raise invalid

    user = await db.get(User, uuid.UUID(user_id))
    if not user or not user.is_active or not user.is_verified:
        raise invalid

    membership = await db.scalar(
        select(Membership).where(Membership.user_id == user.id).limit(1)
    )
    org_id = str(membership.org_id) if membership else str(_DEMO_ORG_ID)

    return TokenResponse(
        access_token=create_access_token(str(user.id), org_id),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(token: str = Depends(oauth2_scheme)) -> None:
    """Odjava — poništava access token na serveru (blacklist)."""
    blacklist_token(token)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> User:
    """Vrati podatke trenutno prijavljenog korisnika."""
    return current_user


# --------------------------------------------------------------------------- #
# Email template                                                               #
# --------------------------------------------------------------------------- #

def _verification_html(name: str, url: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="hr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f7fb;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f7fb;padding:48px 16px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border:1px solid rgba(255,255,255,0.07);border-radius:12px;overflow:hidden">
        <tr>
          <td style="padding:32px 40px 24px;border-bottom:1px solid rgba(255,255,255,0.07)">
            <div style="display:flex;align-items:center;gap:10px">
              <div style="width:32px;height:32px;background:#1a5699;border-radius:8px;display:inline-block;
                          text-align:center;line-height:32px;font-size:16px">⚡</div>
              <span style="font-size:17px;font-weight:700;color:#142238;letter-spacing:-0.3px;vertical-align:middle;margin-left:10px">Ingenium</span>
            </div>
          </td>
        </tr>
        <tr>
          <td style="padding:36px 40px">
            <p style="color:#56657c;font-size:13px;margin:0 0 8px">Pozdrav, {name}</p>
            <h1 style="color:#142238;font-size:22px;font-weight:700;margin:0 0 20px;letter-spacing:-0.5px">
              Potvrdi svoju email adresu
            </h1>
            <p style="color:#56657c;font-size:14px;line-height:1.6;margin:0 0 28px">
              Netko (vjerojatno ti) se registrirao na Ingenium s ovom email adresom.
              Klikni gumb ispod da aktiviraš račun. Link vrijedi {_VERIFY_TOKEN_HOURS} sati.
            </p>
            <a href="{url}"
               style="display:inline-block;background:#1a5699;color:#ffffff;padding:13px 28px;
                      border-radius:8px;text-decoration:none;font-weight:600;font-size:14px">
              Potvrdi email →
            </a>
            <p style="color:#93a1b5;font-size:12px;margin:24px 0 0;line-height:1.5">
              Ako nisi tražio/la pristup, ignorij ovaj email.<br>
              Link: <a href="{url}" style="color:#1a5699">{url}</a>
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 40px;border-top:1px solid rgba(255,255,255,0.07)">
            <p style="color:#93a1b5;font-size:11px;margin:0;font-family:monospace">
              Ingenium · AI Quote &amp; Procurement Platform
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _otp_html(name: str, code: str, expire_seconds: int) -> str:
    first_name = name.split()[0] if name else name
    expire_label = f"{expire_seconds}s" if expire_seconds < 60 else f"{expire_seconds // 60} min"
    # Individual digit cells — gmail-safe bgcolor on td
    digits_html = "".join(
        f'<td align="center" valign="middle" width="52" height="64"'
        f' bgcolor="#ffffff"'
        f' style="font-family:Courier New,monospace;font-size:32px;font-weight:700;'
        f'color:#1a5699;border:2px solid #cdd8e6;border-radius:10px;'
        f'padding:0 6px;mso-line-height-rule:exactly;line-height:64px;">'
        f'{d}</td>'
        f'<td width="8"></td>'
        for d in code
    )
    return f"""<!DOCTYPE html>
<html lang="hr" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>Kod za prijavu — Ingenium</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f7fb;width:100%;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#f4f7fb">
<tr><td align="center" style="padding:48px 16px 64px;">
<table role="presentation" width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;">

  <!--  LOGO  -->
  <tr>
    <td style="padding-bottom:32px;">
      <table role="presentation" cellpadding="0" cellspacing="0">
        <tr>
          <td width="36" height="36" align="center" valign="middle" bgcolor="#1a5699"
              style="border-radius:9px;font-size:18px;line-height:36px;mso-line-height-rule:exactly;">
            ⚡
          </td>
          <td style="padding-left:10px;font-family:Arial,Helvetica,sans-serif;
                      font-size:18px;font-weight:700;color:#1a5699;letter-spacing:-0.3px;">
            Ingenium
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!--  CARD  -->
  <tr>
    <td bgcolor="#ffffff" style="border-radius:20px;border:1px solid #e2e8f0;overflow:hidden;">

      <!--  green top strip  -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td bgcolor="#1a5699" height="3" style="font-size:0;line-height:0;">&nbsp;</td>
        </tr>
      </table>

      <!--  body padding  -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding:44px 48px 40px;">

            <!--  label  -->
            <p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;
                        font-size:11px;font-weight:700;letter-spacing:0.14em;
                        text-transform:uppercase;color:#1a5699;">
              Sigurnosna provjera
            </p>

            <!--  headline  -->
            <h1 style="margin:0 0 14px;font-family:Arial,Helvetica,sans-serif;
                        font-size:26px;font-weight:800;color:#142238;
                        letter-spacing:-0.6px;line-height:1.2;">
              Vaš kod za<br>prijavu je spreman
            </h1>

            <!--  body text  -->
            <p style="margin:0 0 36px;font-family:Arial,Helvetica,sans-serif;
                        font-size:14px;color:#56657c;line-height:1.75;">
              Hej <strong style="color:#56657c;">{first_name}</strong> — unesite
              kod ispod da biste ušli u Ingenium.
              Vrijedi samo <strong style="color:#142238;">{expire_label}</strong>
              i može se iskoristiti jednom.
            </p>

            <!--  CODE BOX  -->
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                   style="margin-bottom:32px;">
              <tr>
                <td bgcolor="#eef4ff" style="border-radius:16px;border:1px solid #e2e8f0;
                                              padding:28px 24px;">
                  <p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;
                              font-size:10px;font-weight:700;letter-spacing:0.16em;
                              text-transform:uppercase;color:#93a1b5;text-align:center;">
                    Jednokratni kod · {expire_label}
                  </p>
                  <table role="presentation" cellpadding="0" cellspacing="0"
                         align="center" style="margin:0 auto;">
                    <tr>{digits_html}</tr>
                  </table>
                </td>
              </tr>
            </table>

            <!--  DIVIDER  -->
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                   style="margin-bottom:24px;">
              <tr>
                <td bgcolor="#e2e8f0" height="1" style="font-size:0;line-height:0;">&nbsp;</td>
              </tr>
            </table>

            <!--  META ROW  -->
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                   style="margin-bottom:28px;">
              <tr>
                <td width="33%" align="center">
                  <p style="margin:0 0 4px;font-family:Arial,sans-serif;font-size:10px;
                              letter-spacing:0.1em;text-transform:uppercase;color:#93a1b5;">
                    Vrijedi
                  </p>
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:16px;
                              font-weight:700;color:#1a8055;">
                    {expire_label}
                  </p>
                </td>
                <td width="1" bgcolor="#e2e8f0">&nbsp;</td>
                <td width="33%" align="center">
                  <p style="margin:0 0 4px;font-family:Arial,sans-serif;font-size:10px;
                              letter-spacing:0.1em;text-transform:uppercase;color:#93a1b5;">
                    Upotreba
                  </p>
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:16px;
                              font-weight:700;color:#1a8055;">
                    1×
                  </p>
                </td>
                <td width="1" bgcolor="#e2e8f0">&nbsp;</td>
                <td width="33%" align="center">
                  <p style="margin:0 0 4px;font-family:Arial,sans-serif;font-size:10px;
                              letter-spacing:0.1em;text-transform:uppercase;color:#93a1b5;">
                    Platforma
                  </p>
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:16px;
                              font-weight:700;color:#1a8055;">
                    Ingenium
                  </p>
                </td>
              </tr>
            </table>

            <!--  SECURITY NOTICE  -->
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td bgcolor="#eef4ff"
                    style="border-radius:10px;border:1px solid #e2e8f0;
                            border-left:3px solid #1a5699;padding:14px 18px;">
                  <p style="margin:0;font-family:Arial,Helvetica,sans-serif;
                              font-size:12px;color:#56657c;line-height:1.7;">
                    <strong style="color:#1a8055;">Niste tražili ovaj kod?</strong>
                    Netko je unio vašu lozinku. Ne dijelite kod ni s kim.
                    Odmah promijenite lozinku i kontaktirajte support.
                  </p>
                </td>
              </tr>
            </table>

          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!--  FOOTER  -->
  <tr>
    <td style="padding:22px 2px 0;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="font-family:Arial,sans-serif;font-size:11px;
                      color:#cdd8e6;line-height:1.6;">
            Ingenium · AI Quote &amp; Procurement
          </td>
          <td align="right" style="font-family:Arial,sans-serif;font-size:11px;
                                    color:#cdd8e6;">
            ingeniumtrade.hr
          </td>
        </tr>
      </table>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>"""
