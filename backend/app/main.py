"""
FastAPI application entry point.

Wires up:
  - middleware
  - exception handlers
  - API routes (/api/v1/*)
  - lifespan (startup/shutdown)
  - static frontend serving (the Ingenium frontend)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware

configure_logging()
logger = logging.getLogger(__name__)

_LOGIN_HTML = """<!DOCTYPE html>
<html lang="hr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Ingenium</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
      rel="stylesheet" media="print" onload="this.media='all'">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{
  min-height:100vh;
  display:grid;
  grid-template-columns:1fr 1fr;
  background:#080a09;
  font-family:'Inter',system-ui,sans-serif;
  color:#e8ede9;
}
/* Lijeva strana — branding */
.brand{
  display:flex;
  flex-direction:column;
  justify-content:space-between;
  padding:48px;
  background:linear-gradient(145deg,#0f1a12 0%,#0a1a0d 60%,#091409 100%);
  border-right:1px solid #1a2a1c;
  position:relative;
  overflow:hidden;
}
.brand::before{
  content:'';
  position:absolute;
  width:500px;height:500px;
  background:radial-gradient(circle,rgba(168,244,184,0.07) 0%,transparent 70%);
  top:-100px;left:-100px;
  pointer-events:none;
}
.brand-logo{display:flex;align-items:center;gap:12px}
.brand-icon{
  width:40px;height:40px;
  background:#a8f4b8;
  border-radius:10px;
  display:flex;align-items:center;justify-content:center;
  font-size:20px;
  box-shadow:0 0 24px rgba(168,244,184,0.3);
}
.brand-name{font-size:20px;font-weight:700;letter-spacing:-0.5px}
.brand-hero{padding:20px 0 40px}
.brand-tagline{
  font-size:32px;font-weight:700;
  line-height:1.2;
  letter-spacing:-1px;
  color:#e8ede9;
  margin-bottom:16px;
}
.brand-tagline span{color:#a8f4b8}
.brand-desc{font-size:14px;color:#5a7a5e;line-height:1.7;max-width:340px}
.brand-stats{display:flex;gap:32px}
.stat-value{font-size:24px;font-weight:700;color:#a8f4b8}
.stat-label{font-size:12px;color:#4a6a4e;margin-top:2px}

/* Desna strana — forma */
.form-side{
  display:flex;
  align-items:center;
  justify-content:center;
  padding:48px 40px;
  background:#0a0c0b;
}
.form-box{width:100%;max-width:380px}
.form-heading{font-size:26px;font-weight:700;letter-spacing:-0.5px;margin-bottom:8px}
.form-sub{font-size:14px;color:#5a6a5e;margin-bottom:32px}
.field{margin-bottom:18px}
.field-label{
  display:block;font-size:12px;font-weight:500;
  color:#6a7a6e;letter-spacing:0.03em;
  text-transform:uppercase;margin-bottom:7px;
}
.field-input{
  width:100%;
  padding:12px 16px;
  background:#141614;
  border:1px solid #252825;
  border-radius:8px;
  color:#e8ede9;
  font-size:14px;
  font-family:'Inter',system-ui,sans-serif;
  outline:none;
  transition:border-color .15s, box-shadow .15s;
}
.field-input::placeholder{color:#3a4a3e}
.field-input:focus{border-color:#a8f4b8;box-shadow:0 0 0 3px rgba(168,244,184,0.08)}
#err{
  display:none;
  background:rgba(244,122,106,.08);
  border:1px solid rgba(244,122,106,.25);
  border-left:3px solid #f47a6a;
  border-radius:6px;
  padding:11px 14px;
  color:#f47a6a;
  font-size:13px;
  margin-bottom:20px;
}
.btn-login{
  width:100%;
  padding:13px;
  background:#a8f4b8;
  color:#051008;
  border:none;
  border-radius:8px;
  font-size:15px;
  font-weight:600;
  cursor:pointer;
  font-family:'Inter',system-ui,sans-serif;
  letter-spacing:-0.2px;
  transition:background .15s, transform .1s;
  margin-top:4px;
}
.btn-login:hover:not(:disabled){background:#7ee89a;transform:translateY(-1px)}
.btn-login:active{transform:translateY(0)}
.btn-login:disabled{opacity:.45;cursor:not-allowed;transform:none}

/* Mobile */
@media(max-width:680px){
  body{grid-template-columns:1fr}
  .brand{display:none}
  .form-side{padding:40px 24px}
}
</style>
</head>
<body>

<div class="brand">
  <div class="brand-logo">
    <div class="brand-icon">⚡</div>
    <div class="brand-name">Ingenium</div>
  </div>
  <div class="brand-hero">
    <div class="brand-tagline">Ponude koje<br>zaključuju<br><span>poslove.</span></div>
    <div class="brand-desc">
      Od RFQ-a do profitabilne ponude za nekoliko minuta.
      AI parsira, katalog matchira, vi potpisujete.
    </div>
  </div>
  <div class="brand-stats">
    <div><div class="stat-value">80%</div><div class="stat-label">brže od ručnog rada</div></div>
    <div><div class="stat-value">27</div><div class="stat-label">EU VAT jurisdikcija</div></div>
    <div><div class="stat-value">∞</div><div class="stat-label">ponuda</div></div>
  </div>
</div>

<div class="form-side">
  <div class="form-box">
    <div class="form-heading">Dobrodošao natrag</div>
    <div class="form-sub">Prijavite se u Ingenium</div>

    <div id="err"></div>

    <div class="field">
      <label class="field-label" for="email">Email</label>
      <input class="field-input" id="email" type="email"
             placeholder="ime@ingeniumtrade.hr"
             autocomplete="email"
             onkeydown="if(event.key==='Enter')document.getElementById('pass').focus()">
    </div>
    <div class="field">
      <label class="field-label" for="pass">Lozinka</label>
      <input class="field-input" id="pass" type="password"
             placeholder="••••••••"
             autocomplete="current-password"
             onkeydown="if(event.key==='Enter')doLogin()">
    </div>

    <button class="btn-login" id="btn" onclick="doLogin()">Prijava &rarr;</button>
  </div>
</div>

<script>
async function doLogin(){
  const email=document.getElementById('email').value.trim();
  const pass=document.getElementById('pass').value;
  const err=document.getElementById('err');
  const btn=document.getElementById('btn');
  err.style.display='none';
  if(!email||!pass){err.textContent='Unesite email i lozinku.';err.style.display='block';return;}
  btn.disabled=true;btn.textContent='Prijava…';
  try{
    const r=await fetch('/api/v1/auth/login',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email,password:pass})
    });
    const d=await r.json();
    if(!r.ok){
      const msg=d.detail||'Neispravni podaci.';
      err.textContent=msg;err.style.display='block';
      return;
    }
    localStorage.setItem('aqp_token',d.access_token);
    localStorage.setItem('aqp_refresh',d.refresh_token);
    window.location.href='/';
  }catch(e){
    err.textContent='Greška veze sa serverom.';err.style.display='block';
  }finally{
    btn.disabled=false;btn.textContent='Prijava →';
  }
}

// Već prijavljen? Preskočimo login.
const t=localStorage.getItem('aqp_token');
if(t){
  fetch('/api/v1/auth/me',{headers:{'Authorization':'Bearer '+t}})
    .then(r=>{if(r.ok)window.location.href='/'})
    .catch(()=>{});
}

document.getElementById('email').focus();
</script>
</body>
</html>"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("starting_application", extra={"env": settings.ENV})
    if "sqlite" in settings.DATABASE_URL:
        from app.db.session import _patch_metadata_for_sqlite
        _patch_metadata_for_sqlite()
        logger.info("sqlite_pg_types_patched")
    yield
    logger.info("shutting_down_application")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Quote & Procurement Platform API",
        description="Backend za RFQ → ponuda pipeline.",
        version="0.1.0",
        docs_url="/api/docs" if settings.ENV != "production" else None,
        redoc_url="/api/redoc" if settings.ENV != "production" else None,
        openapi_url="/api/openapi.json" if settings.ENV != "production" else None,
        lifespan=lifespan,
    )

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    # API routes (prefiks /api/v1)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # Static frontend serving
    # Frontend dir je mountan na /app/static_frontend u containeru
    # ili je lokalno na ../frontend
    frontend_dir = Path("/app/static_frontend")
    if not frontend_dir.exists():
        frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"

    if frontend_dir.exists():
        index_file = frontend_dir / "index.html"

        _no_cache = {"Cache-Control": "no-store, no-cache, must-revalidate"}

        @app.get("/login", include_in_schema=False)
        async def login_page() -> HTMLResponse:
            from fastapi.responses import HTMLResponse
            return HTMLResponse(_LOGIN_HTML, headers=_no_cache)

        @app.get("/", include_in_schema=False)
        async def root() -> FileResponse:
            return FileResponse(index_file, headers=_no_cache)

        app.mount(
            "/static",
            StaticFiles(directory=str(frontend_dir)),
            name="static",
        )
        logger.info("serving_frontend_from", extra={"path": str(frontend_dir)})
    else:
        logger.warning("frontend_dir_not_found", extra={"path": str(frontend_dir)})

        @app.get("/", include_in_schema=False)
        async def root() -> dict:
            return {
                "message": "AI Quote Platform API",
                "docs": "/api/docs",
                "frontend": "not found — provjeri da postoji frontend/index.html",
            }

    return app


app = create_app()
