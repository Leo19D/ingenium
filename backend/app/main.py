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
<link href="https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;1,300&display=swap"
      rel="stylesheet" media="print" onload="this.media='all'">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --green:#a8f4b8;--green-dim:rgba(168,244,184,0.08);--green-glow:rgba(168,244,184,0.18);
  --bg:#07090a;--surface:#0e1210;--border:#1c221e;--border2:#263029;
  --text:#ddeadf;--text2:#7a9480;--text3:#3d5040;
  --red:#f47a6a;--red-dim:rgba(244,122,106,0.1);
}
*{font-family:'Inter',system-ui,sans-serif}
body{min-height:100vh;display:grid;grid-template-columns:55% 45%;background:var(--bg);color:var(--text)}

/* ── LEFT PANEL ── */
.panel-left{
  position:relative;overflow:hidden;
  display:flex;flex-direction:column;justify-content:space-between;
  padding:52px 56px;
  background:var(--surface);
  border-right:1px solid var(--border);
}
/* subtle dot grid */
.panel-left::before{
  content:'';position:absolute;inset:0;
  background-image:radial-gradient(circle,#1e2a20 1px,transparent 1px);
  background-size:28px 28px;opacity:.5;pointer-events:none;
}
/* glow orb */
.panel-left::after{
  content:'';position:absolute;
  width:600px;height:600px;border-radius:50%;
  background:radial-gradient(circle,rgba(168,244,184,0.06) 0%,transparent 65%);
  top:-120px;left:-80px;pointer-events:none;
}
.p-logo{display:flex;align-items:center;gap:11px;position:relative;z-index:1}
.p-logo-mark{
  width:38px;height:38px;border-radius:9px;
  background:var(--green);
  display:flex;align-items:center;justify-content:center;
  font-size:18px;
  box-shadow:0 0 0 1px rgba(168,244,184,.3),0 0 20px rgba(168,244,184,.2);
}
.p-logo-name{font-size:18px;font-weight:700;letter-spacing:-.4px}
.p-logo-badge{
  margin-left:auto;
  font-size:10px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;
  color:var(--green);background:var(--green-dim);
  border:1px solid rgba(168,244,184,.2);
  border-radius:20px;padding:3px 10px;
}
.p-body{position:relative;z-index:1;padding:0 0 20px}
.p-eyebrow{
  font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;
  color:var(--green);margin-bottom:20px;
  display:flex;align-items:center;gap:8px;
}
.p-eyebrow::before{content:'';width:20px;height:1px;background:var(--green);opacity:.6}
.p-headline{
  font-size:44px;font-weight:800;line-height:1.08;letter-spacing:-2px;
  color:var(--text);margin-bottom:22px;
}
.p-headline em{font-style:normal;color:var(--green)}
.p-lead{font-size:15px;font-weight:300;color:var(--text2);line-height:1.75;max-width:360px}
.p-features{display:flex;flex-direction:column;gap:14px;position:relative;z-index:1}
.feat{display:flex;align-items:flex-start;gap:14px}
.feat-icon{
  width:32px;height:32px;flex-shrink:0;
  background:var(--green-dim);border:1px solid rgba(168,244,184,.15);
  border-radius:8px;display:flex;align-items:center;justify-content:center;
  font-size:14px;margin-top:1px;
}
.feat-title{font-size:13px;font-weight:600;color:var(--text);margin-bottom:2px}
.feat-desc{font-size:12px;color:var(--text3);line-height:1.5}

/* ── RIGHT PANEL ── */
.panel-right{
  display:flex;align-items:center;justify-content:center;
  padding:52px 56px;background:var(--bg);
}
.form-wrap{width:100%;max-width:360px}
.form-title{font-size:24px;font-weight:700;letter-spacing:-.6px;margin-bottom:6px}
.form-sub{font-size:13px;color:var(--text2);margin-bottom:36px;font-weight:400}
.field{margin-bottom:16px}
.field-label{
  display:block;font-size:11px;font-weight:600;letter-spacing:.07em;
  text-transform:uppercase;color:var(--text2);margin-bottom:7px;
}
.field-input{
  width:100%;padding:12px 15px;
  background:#0c100e;
  border:1px solid var(--border2);
  border-radius:9px;
  color:var(--text);font-size:14px;font-weight:400;
  outline:none;transition:border-color .15s,box-shadow .15s;
}
.field-input::placeholder{color:var(--text3)}
.field-input:focus{border-color:var(--green);box-shadow:0 0 0 3px var(--green-dim)}
#err{
  display:none;
  border-left:3px solid var(--red);
  background:var(--red-dim);
  border-radius:0 7px 7px 0;
  padding:11px 14px;font-size:13px;color:var(--red);margin-bottom:18px;
}
.btn{
  width:100%;padding:13px 20px;margin-top:8px;
  background:var(--green);color:#041008;
  border:none;border-radius:9px;
  font-size:14px;font-weight:700;letter-spacing:-.1px;
  cursor:pointer;
  display:flex;align-items:center;justify-content:center;gap:8px;
  transition:background .15s,box-shadow .15s,transform .1s;
}
.btn:hover:not(:disabled){
  background:#85eea2;
  box-shadow:0 0 24px var(--green-glow);
  transform:translateY(-1px);
}
.btn:active:not(:disabled){transform:translateY(0)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-arrow{font-size:16px;transition:transform .15s}
.btn:hover .btn-arrow{transform:translateX(3px)}
.divider{display:flex;align-items:center;gap:12px;margin:24px 0}
.divider::before,.divider::after{content:'';flex:1;height:1px;background:var(--border)}
.divider span{font-size:11px;color:var(--text3)}

@media(max-width:780px){
  body{grid-template-columns:1fr}
  .panel-left{display:none}
  .panel-right{padding:40px 28px}
}
</style>
</head>
<body>

<div class="panel-left">
  <div class="p-logo">
    <div class="p-logo-mark">⚡</div>
    <div class="p-logo-name">Ingenium</div>
    <div class="p-logo-badge">Beta</div>
  </div>

  <div class="p-body">
    <div class="p-eyebrow">AI Procurement Platform</div>
    <div class="p-headline">Ponude koje<br>zaključuju<br><em>poslove.</em></div>
    <div class="p-lead">
      Od RFQ-a do profitabilne ponude za nekoliko minuta.<br>
      AI parsira dokumente, katalog matchira artikle,<br>vi potpisujete i šaljete.
    </div>
  </div>

  <div class="p-features">
    <div class="feat">
      <div class="feat-icon">📄</div>
      <div><div class="feat-title">Automatski parsing</div><div class="feat-desc">PDF, XLSX, DOCX troškovnici → strukturirane stavke u sekundama</div></div>
    </div>
    <div class="feat">
      <div class="feat-icon">🔗</div>
      <div><div class="feat-title">Katalog matching</div><div class="feat-desc">4-stage matching: SKU → fuzzy → embedding → AI ranker</div></div>
    </div>
    <div class="feat">
      <div class="feat-icon">🌍</div>
      <div><div class="feat-title">Multi-currency · 27 EU VAT</div><div class="feat-desc">Deterministični pricing engine, nikad LLM za matematiku</div></div>
    </div>
  </div>
</div>

<div class="panel-right">
  <div class="form-wrap">
    <div class="form-title">Dobro došli natrag</div>
    <div class="form-sub">Prijavite se u svoj Ingenium račun</div>

    <div id="err"></div>

    <div class="field">
      <label class="field-label" for="email">Email adresa</label>
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

    <button class="btn" id="btn" onclick="doLogin()">
      <span>Prijava</span>
      <span class="btn-arrow">→</span>
    </button>
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
  btn.disabled=true;btn.querySelector('span').textContent='Prijava…';
  try{
    const r=await fetch('/api/v1/auth/login',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email,password:pass})
    });
    const d=await r.json();
    if(!r.ok){err.textContent=d.detail||'Neispravni podaci za prijavu.';err.style.display='block';return;}
    localStorage.setItem('aqp_token',d.access_token);
    localStorage.setItem('aqp_refresh',d.refresh_token);
    window.location.href='/';
  }catch(e){
    err.textContent='Greška veze sa serverom.';err.style.display='block';
  }finally{
    btn.disabled=false;btn.querySelector('span').textContent='Prijava';
  }
}
const t=localStorage.getItem('aqp_token');
if(t){fetch('/api/v1/auth/me',{headers:{'Authorization':'Bearer '+t}}).then(r=>{if(r.ok)window.location.href='/'}).catch(()=>{})}
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
