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
<title>Prijava — Ingenium</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;1,300&display=swap"
      rel="stylesheet" media="print" onload="this.media='all'">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --green:#a8f4b8;--green-dim:rgba(168,244,184,0.08);--green-glow:rgba(168,244,184,0.18);
  --bg:#07090a;--surface:#0d110f;--border:#1a2019;--border2:#243028;
  --text:#ddeadf;--text2:#7a9480;--text3:#3d5040;
  --red:#f47a6a;--red-dim:rgba(244,122,106,0.08);
  --amber:#f4c56a;--amber-dim:rgba(244,197,106,0.08);
}
*{font-family:'Inter',system-ui,sans-serif}
html,body{height:100%}
body{display:grid;grid-template-columns:55% 45%;background:var(--bg);color:var(--text)}

/* ── LEFT PANEL ── */
.panel-left{
  position:relative;overflow:hidden;
  display:flex;flex-direction:column;justify-content:space-between;
  padding:52px 56px;
  background:var(--surface);
  border-right:1px solid var(--border);
}
.panel-left::before{
  content:'';position:absolute;inset:0;
  background-image:radial-gradient(circle,#1c2a1e 1px,transparent 1px);
  background-size:28px 28px;opacity:.4;pointer-events:none;
}
.panel-left::after{
  content:'';position:absolute;
  width:700px;height:700px;border-radius:50%;
  background:radial-gradient(circle,rgba(168,244,184,0.055) 0%,transparent 60%);
  top:-160px;left:-120px;pointer-events:none;
}
.p-logo{display:flex;align-items:center;gap:11px;position:relative;z-index:1}
.p-logo-mark{
  width:36px;height:36px;border-radius:8px;
  background:var(--green);
  display:flex;align-items:center;justify-content:center;font-size:17px;
  box-shadow:0 0 0 1px rgba(168,244,184,.25),0 0 18px rgba(168,244,184,.18);
}
.p-logo-name{font-size:17px;font-weight:700;letter-spacing:-.4px}
.p-logo-badge{
  margin-left:auto;font-size:9px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
  color:var(--green);background:var(--green-dim);
  border:1px solid rgba(168,244,184,.18);border-radius:20px;padding:3px 9px;
}
.p-body{position:relative;z-index:1;padding:0 0 20px}
.p-eyebrow{
  font-size:11px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;
  color:var(--green);margin-bottom:18px;
  display:flex;align-items:center;gap:8px;
}
.p-eyebrow::before{content:'';width:18px;height:1px;background:var(--green);opacity:.5}
.p-headline{
  font-size:42px;font-weight:800;line-height:1.07;letter-spacing:-2px;
  color:var(--text);margin-bottom:20px;
}
.p-headline em{font-style:normal;color:var(--green)}
.p-lead{font-size:14px;font-weight:300;color:var(--text2);line-height:1.8;max-width:340px}
.p-features{display:flex;flex-direction:column;gap:12px;position:relative;z-index:1}
.feat{display:flex;align-items:flex-start;gap:13px}
.feat-icon{
  width:30px;height:30px;flex-shrink:0;
  background:var(--green-dim);border:1px solid rgba(168,244,184,.12);
  border-radius:7px;display:flex;align-items:center;justify-content:center;
  font-size:13px;margin-top:1px;
}
.feat-text{}
.feat-title{font-size:13px;font-weight:600;color:var(--text);margin-bottom:2px}
.feat-desc{font-size:11.5px;color:var(--text3);line-height:1.5}
.p-footer{position:relative;z-index:1}
.p-footer-line{
  font-size:11px;color:var(--text3);
  display:flex;align-items:center;gap:6px;
}
.p-footer-dot{width:5px;height:5px;border-radius:50%;background:var(--green);opacity:.6}

/* ── RIGHT PANEL ── */
.panel-right{
  display:flex;align-items:center;justify-content:center;
  padding:52px 52px;background:var(--bg);
}
.form-wrap{width:100%;max-width:350px}

/* status banner */
.banner{
  display:none;
  align-items:flex-start;gap:10px;
  padding:12px 14px;border-radius:9px;margin-bottom:22px;
  font-size:13px;line-height:1.5;
}
.banner.info{
  background:var(--green-dim);border:1px solid rgba(168,244,184,.2);color:var(--green);
}
.banner.warn{
  background:var(--amber-dim);border:1px solid rgba(244,197,106,.2);color:var(--amber);
}
.banner.visible{display:flex}
.banner-icon{font-size:15px;flex-shrink:0;margin-top:1px}

.form-title{font-size:23px;font-weight:700;letter-spacing:-.55px;margin-bottom:5px}
.form-sub{font-size:13px;color:var(--text2);margin-bottom:30px;font-weight:400;line-height:1.5}
.field{margin-bottom:14px}
.field-label{
  display:block;font-size:10.5px;font-weight:600;letter-spacing:.08em;
  text-transform:uppercase;color:var(--text2);margin-bottom:6px;
}
.field-input{
  width:100%;padding:11px 14px;
  background:#0a0e0c;
  border:1px solid var(--border2);
  border-radius:8px;
  color:var(--text);font-size:14px;
  outline:none;transition:border-color .15s,box-shadow .15s;
}
.field-input::placeholder{color:var(--text3)}
.field-input:focus{border-color:rgba(168,244,184,.5);box-shadow:0 0 0 3px var(--green-dim)}
.field-input.shake{animation:shake .35s ease}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-5px)}75%{transform:translateX(5px)}}

#err{
  display:none;
  border-left:3px solid var(--red);background:var(--red-dim);
  border-radius:0 7px 7px 0;
  padding:10px 13px;font-size:13px;color:var(--red);margin-bottom:16px;
  line-height:1.45;
}
.btn{
  width:100%;padding:12px 20px;margin-top:6px;
  background:var(--green);color:#041008;
  border:none;border-radius:8px;
  font-size:14px;font-weight:700;
  cursor:pointer;
  display:flex;align-items:center;justify-content:center;gap:8px;
  transition:background .15s,box-shadow .15s,transform .1s,opacity .15s;
}
.btn:hover:not(:disabled){
  background:#8ff5ae;box-shadow:0 0 28px var(--green-glow);transform:translateY(-1px);
}
.btn:active:not(:disabled){transform:translateY(0);box-shadow:none}
.btn:disabled{opacity:.35;cursor:not-allowed}
.btn-arrow{font-size:15px;transition:transform .15s}
.btn:hover:not(:disabled) .btn-arrow{transform:translateX(3px)}
.form-footer{margin-top:20px;font-size:11.5px;color:var(--text3);text-align:center;line-height:1.6}
.form-footer strong{color:var(--text2);font-weight:500}

@media(max-width:780px){
  body{grid-template-columns:1fr}
  .panel-left{display:none}
  .panel-right{padding:40px 24px}
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
      Od RFQ dokumenta do profitabilne ponude za nekoliko minuta.
      AI parsira, katalog matchira, vi potpisujete.
    </div>
  </div>

  <div class="p-features">
    <div class="feat">
      <div class="feat-icon">📄</div>
      <div class="feat-text">
        <div class="feat-title">Automatski parsing</div>
        <div class="feat-desc">PDF, XLSX, DOCX troškovnici → strukturirane stavke</div>
      </div>
    </div>
    <div class="feat">
      <div class="feat-icon">🔗</div>
      <div class="feat-text">
        <div class="feat-title">4-stage catalog matching</div>
        <div class="feat-desc">SKU → fuzzy → embedding → AI ranker</div>
      </div>
    </div>
    <div class="feat">
      <div class="feat-icon">🌍</div>
      <div class="feat-text">
        <div class="feat-title">Multi-currency · 27 EU VAT</div>
        <div class="feat-desc">Deterministični pricing, nikad LLM za matematiku</div>
      </div>
    </div>
  </div>

  <div class="p-footer">
    <div class="p-footer-line">
      <div class="p-footer-dot"></div>
      <span>Pristup ograničen · @ingeniumtrade.hr</span>
    </div>
  </div>
</div>

<div class="panel-right">
  <div class="form-wrap">

    <div class="banner info" id="banner-logout">
      <span class="banner-icon">✓</span>
      <span>Uspješno ste se odjavili.</span>
    </div>
    <div class="banner warn" id="banner-expired">
      <span class="banner-icon">⚠</span>
      <span>Sesija je istekla. Prijavite se ponovo.</span>
    </div>
    <div class="banner info" id="banner-verified">
      <span class="banner-icon">✓</span>
      <span>Email potvrđen. Možete se prijaviti.</span>
    </div>

    <div class="form-title">Dobro došli natrag</div>
    <div class="form-sub" id="form-sub">Prijavite se u svoj Ingenium račun</div>

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
      <span id="btn-label">Prijava</span>
      <span class="btn-arrow">→</span>
    </button>

    <div class="form-footer">
      Pristup jedino za <strong>@ingeniumtrade.hr</strong>
    </div>
  </div>
</div>

<script>
(function(){
  const p = new URLSearchParams(location.search);
  if(p.get('reason')==='logout') document.getElementById('banner-logout').classList.add('visible');
  if(p.get('reason')==='expired') document.getElementById('banner-expired').classList.add('visible');
  if(p.get('verified')==='1') document.getElementById('banner-verified').classList.add('visible');
  if(p.toString()) history.replaceState({},'','/login');
  const t = localStorage.getItem('aqp_token');
  if(t){
    fetch('/api/v1/auth/me',{headers:{'Authorization':'Bearer '+t}})
      .then(r=>{ if(r.ok) window.location.href='/'; })
      .catch(()=>{});
  }
  document.getElementById('email').focus();
})();

async function doLogin(){
  const email = document.getElementById('email').value.trim();
  const pass  = document.getElementById('pass').value;
  const err   = document.getElementById('err');
  const btn   = document.getElementById('btn');
  const label = document.getElementById('btn-label');
  err.style.display = 'none';
  if(!email || !pass){
    showErr('Unesite email i lozinku.');
    return;
  }
  btn.disabled = true;
  label.textContent = 'Prijava…';
  try {
    const r = await fetch('/api/v1/auth/login',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({email, password:pass}),
    });
    const d = await r.json();
    if(!r.ok){
      const msg = d.detail || (r.status===429 ? 'Previše pokušaja. Pričekajte minutu.' : 'Neispravni podaci za prijavu.');
      showErr(msg);
      document.getElementById('pass').classList.add('shake');
      setTimeout(()=>document.getElementById('pass').classList.remove('shake'), 400);
      return;
    }
    localStorage.setItem('aqp_token',  d.access_token);
    localStorage.setItem('aqp_refresh', d.refresh_token);
    window.location.href = '/';
  } catch(e) {
    showErr('Greška veze sa serverom. Pokušajte ponovo.');
  } finally {
    btn.disabled = false;
    label.textContent = 'Prijava';
  }
}

function showErr(msg){
  const el = document.getElementById('err');
  el.textContent = msg;
  el.style.display = 'block';
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
