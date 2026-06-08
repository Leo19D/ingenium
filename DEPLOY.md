# Deploy — Ingenium

Arhitektura: **Railway** (backend + frontend, jedan servis) · **Supabase** (Postgres) · **Vercel** (frontend, opcionalno kasnije).

Backend servira i frontend (isti origin) → nema CORS/login komplikacija. Kasnije se frontend može odvojiti na Vercel (vidi zadnju sekciju).

---

## 1. GitHub

```bash
# Kreiraj prazan repo na github.com (BEZ README/gitignore), pa:
git remote add origin https://github.com/<korisnik>/<repo>.git
git push -u origin main
```
`.env` je gitignoran — tajne ne idu na GitHub.

---

## 2. Supabase (baza)

1. Kreiraj projekt na [supabase.com](https://supabase.com). Zapamti **database password**.
2. **Project Settings → Database → Connection string → URI**. Dobiješ:
   ```
   postgresql://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres
   ```
3. Za našu app preoblikuj u **asyncpg** oblik (zamijeni `postgresql://` → `postgresql+asyncpg://`):
   ```
   postgresql+asyncpg://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres
   ```
   To je `DATABASE_URL`. (Koristi **direktnu** vezu na portu 5432, ne pooler 6543 — Railway drži trajni pool.)

Bazu ne trebaš ručno migrirati — backend pri startu pokrene `scripts/init_db.py` (create_all + admin + alembic stamp).

---

## 3. Railway (backend)

1. [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo** → odaberi repo.
2. Railway detektira **root `Dockerfile`**. (Ako pita za build: Dockerfile, context = repo root.)
3. **Variables** — postavi:

   | Varijabla | Vrijednost |
   |---|---|
   | `DATABASE_URL` | `postgresql+asyncpg://postgres:[PW]@db.xxxxx.supabase.co:5432/postgres` |
   | `DB_SSL` | `true` |
   | `SECRET_KEY` | random 64-znak string (`openssl rand -hex 32`) |
   | `ENV` | `production` |
   | `ADMIN_EMAIL` | `leodupanovic1@gmail.com` |
   | `ADMIN_PASSWORD` | tvoja lozinka za prvi login (owner) |
   | `SMTP_HOST` | `smtp.gmail.com` |
   | `SMTP_PORT` | `587` |
   | `SMTP_USER` | `ingeniumtrade@gmail.com` (ili tvoj) |
   | `SMTP_PASSWORD` | Gmail App Password |
   | `SMTP_FROM` | `Ingenium <ingeniumtrade@gmail.com>` |
   | `ANTHROPIC_API_KEY` | (opcionalno — za LLM parsing/email draft) |
   | `BACKEND_CORS_ORIGINS` | (prazno za sad; popuni kad dodaš Vercel) |

4. Deploy. Railway daje URL tipa `https://<app>.up.railway.app`.
5. Otvori taj URL → login stranica → prijavi se s `ADMIN_EMAIL` + `ADMIN_PASSWORD` (+ OTP na mail).

**Napomena — uploadi:** dokumenti se spremaju na disk kontejnera koji se resetira pri redeployu. Za trajnost dodaj Railway **Volume** mountan na `/app/uploads` (Settings → Volumes). RFQ se ionako odmah pretvori u ponudu, pa sirovi file nije kritičan.

---

## 4. Vercel (frontend) — opcionalno, kasnije

Za sad backend (Railway) servira i frontend, pa Vercel nije nužan. Kad poželiš odvojen frontend:

1. Napravi `frontend/config.js`:
   ```js
   window.INGENIUM_API_BASE = "https://<app>.up.railway.app";
   ```
   i u `index.html` dodaj `<script src="config.js"></script>` prije glavne skripte.
2. Vercel → New Project → root `frontend/` → deploy (static).
3. Na Railwayu postavi `BACKEND_CORS_ORIGINS=https://<tvoj>.vercel.app`.
4. Login stranicu (`/login`) treba izložiti i na Vercelu (extract iz backenda) — javi pa to riješimo.

---

## Lokalni dev (podsjetnik)

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000
# frontend: http://localhost:8000 (backend ga servira)
```
