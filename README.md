# AI Quote & Procurement Platform

SaaS platforma koja od ulaznog dokumenta (PDF/XLSX troškovnik, RFQ, email s prilozima) producira strukturiranu, profitabilnu, klijent-spremnu ponudu — multi-currency, multi-tax, multi-language, human-in-the-loop.

**Trenutno stanje:** funkcionalan HTML prototip frontenda (`frontend/index.html`) + backend skeleton (FastAPI + PostgreSQL s pgvector) + kompletna database shema + spec dokument.

> Cijeli engineering blueprint je u [`docs/SPEC.md`](./docs/SPEC.md).

---

## Tri načina korištenja

### 1. Najjednostavnije — samo HTML prototip (bez Dockera, bez baze)

Otvori HTML u browseru. Sve radi (klijenti, dobavljači, skladište, import iz Excela), podaci su in-memory pa nestanu na refresh.

```bash
make demo
# ili ručno:
open frontend/index.html        # macOS
xdg-open frontend/index.html    # Linux
start frontend/index.html       # Windows
```

Ovo je dovoljno da:
- testiraš UI s pravim Excel fajlovima iz svog skladišta i s podacima klijenata/dobavljača
- pokažeš nekome kako platforma izgleda
- istražuješ workflow prije nego što gradiš backend logiku

### 2. Full stack — Docker Compose (Postgres + backend + frontend)

Potreba: instaliran Docker Desktop ili Docker Engine + Compose plugin.

```bash
cp .env.example .env
# Otvori .env i postavi minimalno SECRET_KEY (bilo koji random string, 32+ znakova)
# ANTHROPIC_API_KEY ti treba kad počneš koristiti LLM funkcije, sad ne mora.

make up
```

Pristup:
- **App:** http://localhost:8000 (frontend se servira iz backenda)
- **API docs (Swagger):** http://localhost:8000/api/docs
- **Postgres:** localhost:5432, user `postgres`, password `postgres`, db `quote_platform`

Prva pokretanja: docker compose učitava `infra/docker/postgres/init.sql` → `db/schema.sql` → `db/seed.sql` automatski. Imaš odmah demo organizaciju, klijente, dobavljače, skladišne artikle.

### 3. Samo backend lokalno (Python venv, bez Dockera)

Ako ti je Docker overhead i hoćeš direktno hakirati backend.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# Postavi DATABASE_URL u .env (može biti i sqlite za brzi test)
uvicorn app.main:app --reload
```

---

## Struktura projekta

```
ai-quote-platform/
├── frontend/
│   └── index.html          # Radni HTML prototip (jedan fajl, ~108 KB)
├── backend/
│   ├── app/
│   │   ├── main.py         # FastAPI entry — servira i API i frontend
│   │   ├── config.py       # Settings (Pydantic Settings)
│   │   ├── api/v1/         # API endpoint moduli
│   │   ├── core/           # logging, middleware, exceptions
│   │   ├── db/             # SQLAlchemy modeli, sessija
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── services/       # pricing, tax, llm, matching, ingestion
│   │   └── workers/        # Celery task stubs (za Fazu 2+)
│   ├── alembic/            # migracije
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── db/
│   ├── schema.sql          # Kompletna baza
│   └── seed.sql            # Sample podaci
├── docs/
│   ├── SPEC.md             # Engineering blueprint
│   ├── adr/                # Architecture decisions
│   └── prompts/            # LLM prompt biblioteke
├── infra/
│   └── docker/postgres/init.sql
├── .env.example
├── docker-compose.yml
├── Makefile
└── README.md
```

---

## Najvažnije komande (`make help` za sve)

```bash
make demo             # Otvori HTML prototip u browseru
make up               # Pokreni Docker stack
make down             # Zaustavi
make logs-backend     # Tail backend logova
make shell-db         # psql u bazu
make shell-backend    # Bash u backend kontejneru
make reset-db         # DROP + recreate (gubi podatke!)
make test             # Backend testovi
```

---

## Što sad imaš (Faza 0 — Foundation gotova)

- Multi-tenant database shema (~17 tablica + 2 view-a)
- Pojednostavljen Docker setup koji bootash jednom komandom
- Frontend prototip s 8 ekrana (dashboard, pipeline, dokumenti, katalog, skladište, ponude, klijenti, dobavljači)
- Excel import (Klijenti / Dobavljači / Skladište) s auto column-mapping i preview
- Skeleton koda za ingestion pipeline, pricing engine, tax engine, LLM provider apstrakciju
- Backend dependency lista (FastAPI, SQLAlchemy, Anthropic, instructor, pdfplumber, openpyxl, ...)

## Što treba sljedeće (Faza 1)

1. **Spojiti frontend s backendom** (sad je sve in-memory):
   - `POST /api/v1/clients` umjesto DOM-only addClient
   - `POST /api/v1/suppliers` isto
   - `POST /api/v1/stock-items/bulk` za Excel uvoz
   - GET endpointi za inicijalno učitavanje
2. **Auth**: registracija/login → JWT
3. **Document upload**: form-data endpoint za PDF/XLSX
4. **Document parsing**: pdfplumber/openpyxl prvo, LLM fallback drugo
5. **Item matching**: 4-stage pipeline (exact SKU → fuzzy → embedding → LLM ranker)

Detalje u [`docs/SPEC.md`](./docs/SPEC.md) — sve je razloženo po fazama.

---

## Licenca

Proprietary — © Elektro Demo d.o.o., 2026.
