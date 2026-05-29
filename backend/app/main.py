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
<title>Ingenium — Prijava</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{min-height:100vh;display:flex;align-items:center;justify-content:center;
     background:#0d0f0e;font-family:Arial,sans-serif}
.card{width:380px;max-width:94vw;background:#232823;border:1px solid #a8f4b8;
      border-radius:14px;padding:36px}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:28px}
.logo-icon{width:34px;height:34px;background:#a8f4b8;border-radius:8px;
           display:flex;align-items:center;justify-content:center;font-size:17px}
.logo-name{font-size:17px;font-weight:700;color:#e8ede9}
h1{font-size:20px;color:#e8ede9;margin-bottom:6px}
p{font-size:13px;color:#8a9489;margin-bottom:24px}
label{display:block;font-size:12px;color:#8a9489;margin-bottom:5px}
input{width:100%;padding:10px 13px;background:#1a1d1b;border:1px solid #3a4038;
      border-radius:7px;color:#e8ede9;font-size:14px;outline:none;margin-bottom:14px}
input:focus{border-color:#a8f4b8}
button{width:100%;padding:12px;background:#a8f4b8;color:#0a1a0d;border:none;
       border-radius:7px;font-size:15px;font-weight:700;cursor:pointer;margin-top:4px}
button:hover{background:#6bde8a}
button:disabled{opacity:.5;cursor:not-allowed}
#err{display:none;background:rgba(244,122,106,.15);border:1px solid rgba(244,122,106,.4);
     border-radius:6px;padding:9px 13px;color:#f47a6a;font-size:13px;margin-bottom:16px}
.footer{margin-top:18px;text-align:center;font-size:11px;color:#5a6358;line-height:1.6}
.footer span{color:#a8f4b8}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <div class="logo-icon">⚡</div>
    <div class="logo-name">Ingenium</div>
  </div>
  <h1>Dobrodošao natrag</h1>
  <p>Unesite podatke za prijavu</p>
  <div id="err"></div>
  <label>Email</label>
  <input id="email" type="email" placeholder="vas@ingeniumtrade.hr" autocomplete="email">
  <label>Lozinka</label>
  <input id="pass" type="password" placeholder="••••••••" autocomplete="current-password"
         onkeydown="if(event.key==='Enter')doLogin()">
  <button id="btn" onclick="doLogin()">Prijava</button>
  <div class="footer">Pristup samo za <span>@ingeniumtrade.hr</span><br>ili <span>leodupanovic1@gmail.com</span></div>
</div>
<script>
async function doLogin(){
  const email=document.getElementById('email').value.trim();
  const pass=document.getElementById('pass').value;
  const err=document.getElementById('err');
  const btn=document.getElementById('btn');
  err.style.display='none';
  if(!email||!pass){err.textContent='Unesite email i lozinku.';err.style.display='block';return;}
  btn.disabled=true;btn.textContent='Prijava...';
  try{
    const r=await fetch('/api/v1/auth/login',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email,password:pass})});
    const d=await r.json();
    if(!r.ok){err.textContent=d.detail||'Neispravni podaci.';err.style.display='block';return;}
    localStorage.setItem('aqp_token',d.access_token);
    localStorage.setItem('aqp_refresh',d.refresh_token);
    window.location.href='/';
  }catch(e){
    err.textContent='Greška mreže. Provjeri je li server pokrenut.';err.style.display='block';
  }finally{btn.disabled=false;btn.textContent='Prijava';}
}
// Ako već ima token — odmah na app
const t=localStorage.getItem('aqp_token');
if(t){
  fetch('/api/v1/auth/me',{headers:{'Authorization':'Bearer '+t}})
    .then(r=>r.ok?window.location.href='/':null).catch(()=>null);
}
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
