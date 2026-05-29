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
    OTP_EXPIRE_MINUTES,
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
    expires_in_minutes: int = OTP_EXPIRE_MINUTES


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
    user.otp_expires_at = datetime.now(UTC) + timedelta(minutes=OTP_EXPIRE_MINUTES)
    user.otp_attempts = 0
    await db.commit()

    import logging as _logging
    _log = _logging.getLogger(__name__)

    # Timestamp za security alert
    now_str = datetime.now(UTC).strftime("%d.%m.%Y. u %H:%M UTC")

    try:
        await send_email(
            to=email,
            subject="Vaš kod za prijavu — Ingenium",
            html=_otp_html(user.full_name, otp, OTP_EXPIRE_MINUTES),
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

    # Security alert na admin email (fire-and-forget, ne blokira login)
    try:
        await send_email(
            to="ingeniumtrade@gmail.com",
            subject=f"🔐 Login pokušaj — {email}",
            html=_security_alert_html(email, client_ip, now_str),
        )
    except Exception:
        pass  # Alert nije kritičan — ne smije blokirati login

    if settings.ENV == "development":
        _log.warning(f"[DEV] OTP za {email}: {otp}")

    # Otkrivamo samo dio emaila (npr. l***@gmail.com)
    parts = email.split("@")
    masked = parts[0][0] + "***@" + parts[1]
    return LoginStep1Response(
        message=f"Kod je poslan na {masked}",
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
<body style="margin:0;padding:0;background:#0d0f0e;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0f0e;padding:48px 16px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
             style="background:#141716;border:1px solid rgba(255,255,255,0.07);border-radius:12px;overflow:hidden">
        <tr>
          <td style="padding:32px 40px 24px;border-bottom:1px solid rgba(255,255,255,0.07)">
            <div style="display:flex;align-items:center;gap:10px">
              <div style="width:32px;height:32px;background:#a8f4b8;border-radius:8px;display:inline-block;
                          text-align:center;line-height:32px;font-size:16px">⚡</div>
              <span style="font-size:17px;font-weight:700;color:#e8ede9;letter-spacing:-0.3px;vertical-align:middle;margin-left:10px">Ingenium</span>
            </div>
          </td>
        </tr>
        <tr>
          <td style="padding:36px 40px">
            <p style="color:#8a9489;font-size:13px;margin:0 0 8px">Pozdrav, {name}</p>
            <h1 style="color:#e8ede9;font-size:22px;font-weight:700;margin:0 0 20px;letter-spacing:-0.5px">
              Potvrdi svoju email adresu
            </h1>
            <p style="color:#8a9489;font-size:14px;line-height:1.6;margin:0 0 28px">
              Netko (vjerojatno ti) se registrirao na Ingenium s ovom email adresom.
              Klikni gumb ispod da aktiviraš račun. Link vrijedi {_VERIFY_TOKEN_HOURS} sati.
            </p>
            <a href="{url}"
               style="display:inline-block;background:#a8f4b8;color:#0a1a0d;padding:13px 28px;
                      border-radius:8px;text-decoration:none;font-weight:600;font-size:14px">
              Potvrdi email →
            </a>
            <p style="color:#5a6358;font-size:12px;margin:24px 0 0;line-height:1.5">
              Ako nisi tražio/la pristup, ignorij ovaj email.<br>
              Link: <a href="{url}" style="color:#a8f4b8">{url}</a>
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 40px;border-top:1px solid rgba(255,255,255,0.07)">
            <p style="color:#5a6358;font-size:11px;margin:0;font-family:monospace">
              Ingenium · AI Quote &amp; Procurement Platform
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _otp_html(name: str, code: str, expire_minutes: int) -> str:
    first_name = name.split()[0] if name else name
    spaced_code = "  ".join(code)
    return f"""<!DOCTYPE html>
<html lang="hr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kod za prijavu — Ingenium</title>
</head>
<body style="margin:0;padding:0;background:#060908;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#060908;padding:0;">
<tr><td align="center" style="padding:52px 16px 72px;">

  <table width="480" cellpadding="0" cellspacing="0" style="max-width:480px;">

    <!-- Logo row -->
    <tr>
      <td style="padding-bottom:28px;">
        <table cellpadding="0" cellspacing="0"><tr valign="middle">
          <td style="width:38px;height:38px;background:#a8f4b8;border-radius:10px;
                      text-align:center;line-height:38px;font-size:20px;">⚡</td>
          <td style="padding-left:10px;font-family:Arial,sans-serif;font-size:18px;
                      font-weight:700;color:#c8e8ca;letter-spacing:-0.4px;">Ingenium</td>
        </tr></table>
      </td>
    </tr>

    <!-- Main card -->
    <tr>
      <td style="background:#0e1510;border-radius:20px;overflow:hidden;
                  border:1px solid #1e2d20;">

        <!-- Top accent bar -->
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="height:3px;background:linear-gradient(90deg,#a8f4b8 0%,#4dd88a 50%,#a8f4b8 100%);"></td>
          </tr>
        </table>

        <!-- Card body -->
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding:44px 48px 40px;">

              <!-- Eyebrow -->
              <p style="margin:0 0 18px;font-family:Arial,sans-serif;font-size:11px;
                          font-weight:700;letter-spacing:0.12em;text-transform:uppercase;
                          color:#4a7a52;">
                Sigurnosna verifikacija
              </p>

              <!-- Headline -->
              <h1 style="margin:0 0 12px;font-family:Arial,sans-serif;font-size:28px;
                          font-weight:800;color:#e0ece2;letter-spacing:-0.8px;line-height:1.15;">
                Vaš jednokratni<br>kod za prijavu
              </h1>

              <!-- Subtext -->
              <p style="margin:0 0 40px;font-family:Arial,sans-serif;font-size:14px;
                          color:#5a7a5e;line-height:1.7;">
                Hej, <strong style="color:#9abf9c;">{first_name}</strong> —
                unesite ovaj kod da biste pristupili svom Ingenium računu.
                Vrijedi <strong style="color:#c0ddc2;">{expire_minutes}&nbsp;minuta</strong>.
              </p>

              <!-- Code block -->
              <table cellpadding="0" cellspacing="0" width="100%"
                     style="background:#070d09;border-radius:16px;border:1px solid #253528;
                            margin-bottom:36px;">
                <tr>
                  <td style="padding:32px 0;text-align:center;">
                    <p style="margin:0 0 10px;font-family:Arial,sans-serif;font-size:11px;
                                font-weight:600;letter-spacing:0.14em;text-transform:uppercase;
                                color:#374d39;">
                      Jednokratni kod
                    </p>
                    <p style="margin:0;font-family:'Courier New',Courier,monospace;
                                font-size:48px;font-weight:700;letter-spacing:0.25em;
                                color:#a8f4b8;line-height:1;">
                      {spaced_code}
                    </p>
                  </td>
                </tr>
              </table>

              <!-- Info row -->
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="margin-bottom:32px;">
                <tr>
                  <td width="33%" style="text-align:center;padding:0 4px;">
                    <div style="background:#0a0f0b;border:1px solid #1e2a1f;border-radius:10px;padding:14px 8px;">
                      <p style="margin:0 0 4px;font-family:Arial,sans-serif;font-size:10px;
                                  letter-spacing:0.1em;text-transform:uppercase;color:#3a5a3e;">Istječe za</p>
                      <p style="margin:0;font-family:Arial,sans-serif;font-size:15px;
                                  font-weight:700;color:#8ab890;">{expire_minutes} min</p>
                    </div>
                  </td>
                  <td width="33%" style="text-align:center;padding:0 4px;">
                    <div style="background:#0a0f0b;border:1px solid #1e2a1f;border-radius:10px;padding:14px 8px;">
                      <p style="margin:0 0 4px;font-family:Arial,sans-serif;font-size:10px;
                                  letter-spacing:0.1em;text-transform:uppercase;color:#3a5a3e;">Jednokratan</p>
                      <p style="margin:0;font-family:Arial,sans-serif;font-size:15px;
                                  font-weight:700;color:#8ab890;">Da</p>
                    </div>
                  </td>
                  <td width="33%" style="text-align:center;padding:0 4px;">
                    <div style="background:#0a0f0b;border:1px solid #1e2a1f;border-radius:10px;padding:14px 8px;">
                      <p style="margin:0 0 4px;font-family:Arial,sans-serif;font-size:10px;
                                  letter-spacing:0.1em;text-transform:uppercase;color:#3a5a3e;">Platforma</p>
                      <p style="margin:0;font-family:Arial,sans-serif;font-size:15px;
                                  font-weight:700;color:#8ab890;">Ingenium</p>
                    </div>
                  </td>
                </tr>
              </table>

              <!-- Security notice -->
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="background:#06100a;border-radius:12px;
                              border:1px solid #1a2a1d;border-left:3px solid #a8f4b8;
                              padding:16px 20px;">
                    <p style="margin:0;font-family:Arial,sans-serif;font-size:12.5px;
                                color:#4a6a4e;line-height:1.7;">
                      <strong style="color:#7aaa80;">Niste tražili ovaj kod?</strong>
                      Netko je unio vašu lozinku i pokušava pristupiti vašem računu.
                      Ne dijelite ovaj kod ni s kim. Odmah promijenite lozinku.
                    </p>
                  </td>
                </tr>
              </table>

            </td>
          </tr>
        </table>

      </td>
    </tr>

    <!-- Footer -->
    <tr>
      <td style="padding:24px 4px 0;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="font-family:Arial,sans-serif;font-size:11px;color:#2a3c2c;line-height:1.6;">
              Ingenium · AI Quote &amp; Procurement Platform
            </td>
            <td align="right" style="font-family:Arial,sans-serif;font-size:11px;color:#2a3c2c;">
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


def _security_alert_html(email: str, ip: str, timestamp: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="hr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login alert — Ingenium</title>
</head>
<body style="margin:0;padding:0;background:#060908;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#060908;padding:0;">
<tr><td align="center" style="padding:48px 16px 64px;">

  <table width="480" cellpadding="0" cellspacing="0" style="max-width:480px;">

    <!-- Logo -->
    <tr>
      <td style="padding-bottom:24px;">
        <table cellpadding="0" cellspacing="0"><tr valign="middle">
          <td style="width:34px;height:34px;background:#a8f4b8;border-radius:9px;
                      text-align:center;line-height:34px;font-size:17px;">⚡</td>
          <td style="padding-left:10px;font-family:Arial,sans-serif;font-size:16px;
                      font-weight:700;color:#c8e8ca;">Ingenium</td>
          <td style="padding-left:10px;">
            <span style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;
                          letter-spacing:0.08em;text-transform:uppercase;color:#e8a060;
                          background:rgba(232,160,96,0.1);border:1px solid rgba(232,160,96,0.25);
                          border-radius:20px;padding:3px 9px;">Security Alert</span>
          </td>
        </tr></table>
      </td>
    </tr>

    <!-- Alert card -->
    <tr>
      <td style="background:#0f100c;border-radius:20px;overflow:hidden;
                  border:1px solid #2a2618;">

        <!-- Amber accent bar -->
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="height:3px;background:linear-gradient(90deg,#f4c56a 0%,#e8955a 50%,#f4c56a 100%);"></td>
          </tr>
        </table>

        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding:40px 44px 36px;">

              <!-- Icon + headline -->
              <table cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
                <tr valign="middle">
                  <td style="width:48px;height:48px;background:rgba(244,197,106,0.1);
                              border:1px solid rgba(244,197,106,0.25);border-radius:12px;
                              text-align:center;line-height:48px;font-size:22px;">🔐</td>
                  <td style="padding-left:16px;">
                    <p style="margin:0 0 3px;font-family:Arial,sans-serif;font-size:11px;
                                font-weight:700;letter-spacing:0.1em;text-transform:uppercase;
                                color:#7a6a30;">Pokušaj prijave</p>
                    <h2 style="margin:0;font-family:Arial,sans-serif;font-size:20px;
                                font-weight:800;color:#e8e0c8;letter-spacing:-0.4px;">
                      Netko se prijavljuje
                    </h2>
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 28px;font-family:Arial,sans-serif;font-size:14px;
                          color:#7a7050;line-height:1.7;">
                Zabilježena je prijava na Ingenium platformu. OTP kod je poslan korisniku.
                Ako ovo niste vi, odmah reagirajte.
              </p>

              <!-- Detail rows -->
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#0a0b07;border-radius:12px;border:1px solid #222018;
                            margin-bottom:24px;overflow:hidden;">
                <tr style="border-bottom:1px solid #1e1c12;">
                  <td style="padding:14px 20px;font-family:Arial,sans-serif;font-size:11px;
                              font-weight:700;letter-spacing:0.08em;text-transform:uppercase;
                              color:#4a4530;width:40%;">Korisnik</td>
                  <td style="padding:14px 20px;font-family:'Courier New',monospace;font-size:13px;
                              color:#c8c0a0;font-weight:600;">{email}</td>
                </tr>
                <tr style="border-bottom:1px solid #1e1c12;">
                  <td style="padding:14px 20px;font-family:Arial,sans-serif;font-size:11px;
                              font-weight:700;letter-spacing:0.08em;text-transform:uppercase;
                              color:#4a4530;">IP adresa</td>
                  <td style="padding:14px 20px;font-family:'Courier New',monospace;font-size:13px;
                              color:#c8c0a0;">{ip}</td>
                </tr>
                <tr>
                  <td style="padding:14px 20px;font-family:Arial,sans-serif;font-size:11px;
                              font-weight:700;letter-spacing:0.08em;text-transform:uppercase;
                              color:#4a4530;">Vrijeme</td>
                  <td style="padding:14px 20px;font-family:'Courier New',monospace;font-size:13px;
                              color:#c8c0a0;">{timestamp}</td>
                </tr>
              </table>

              <!-- Warning -->
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="background:#0c0a06;border-radius:10px;
                              border:1px solid #2a2216;border-left:3px solid #f4c56a;
                              padding:14px 18px;">
                    <p style="margin:0;font-family:Arial,sans-serif;font-size:12.5px;
                                color:#6a6040;line-height:1.7;">
                      Ako <strong style="color:#a09050;">ne prepoznajete ovu prijavu</strong>,
                      odmah onemogućite račun i promijenite lozinku.
                      Ovaj alert se šalje pri svakom pokušaju prijave.
                    </p>
                  </td>
                </tr>
              </table>

            </td>
          </tr>
        </table>

      </td>
    </tr>

    <!-- Footer -->
    <tr>
      <td style="padding:20px 4px 0;">
        <p style="margin:0;font-family:Arial,sans-serif;font-size:11px;color:#2a2818;line-height:1.6;">
          Ingenium Security · Automatski generiran alert · Ne odgovaraj na ovaj email
        </p>
      </td>
    </tr>

  </table>

</td></tr>
</table>

</body>
</html>"""
