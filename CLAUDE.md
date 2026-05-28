# AI Quote & Procurement Platform

## Što je ovo

SaaS platforma koja od ulaznog dokumenta (PDF/XLSX troškovnik, RFQ) producira strukturiranu, profitabilnu ponudu. Domena: rasvjeta / elektromaterijal. Multi-currency, multi-tax, multi-language, human-in-the-loop.

Solo developer projekt. Odgovaraj na hrvatskom (tehnički termini na engleskom su OK). Cijeni pragmatičnost iznad impresivnosti — pravi, testirani kod, ne buzzword arhitektura.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16 + pgvector + pg_trgm. Pydantic v2.
- **Frontend:** vanilla HTML/CSS/JS u jednom fajlu (`frontend/index.html`). Bez build koraka. Koristi SheetJS (CDN) za Excel. NEMA Reacta/Next.js — namjerno, da ostane jednostavno.
- **Baza:** schema u `db/schema.sql`, seed u `db/seed.sql`. Migracije preko Alembica (`backend/alembic/`).
- **Infra:** Docker Compose (`docker-compose.yml`) — samo postgres + backend. Backend servira frontend statički.

## Komande

```bash
make demo          # otvori frontend/index.html u browseru (bez baze, in-memory)
make up            # Docker: postgres + backend na http://localhost:8000
make down          # zaustavi
make logs-backend  # backend logovi
make shell-db      # psql u bazu
make reset-db      # DROP + recreate baza (gubi podatke)
make test          # backend testovi (pytest)
```

Backend lokalno bez Dockera:
```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Arhitektura — ključne odluke

1. **Nema auth još.** Sve podaci idu u jednu demo organizaciju. Funkcija `app/api/deps.py::get_current_org_id()` vraća fiksni UUID (`00000000-0000-0000-0000-000000000001`, definiran u `db/seed.sql`). Kad dodaješ auth, mijenjaš SAMO tu funkciju da čita iz JWT-a.

2. **LLM samo za parsiranje/matching/tekst.** Matematika (cijene, porezi, marže) je uvijek deterministični Python kod, NIKAD LLM. Vidi `app/services/pricing/` i `app/services/tax/`.

3. **Frontend dual-mode.** `frontend/index.html` detektira je li backend dostupan (`checkApi()` gađa `/api/v1/health`). Ako da → šalje fetch na API. Ako ne → in-memory fallback (demo mode). Zato `make demo` radi bez ičega.

4. **Bulk import.** Excel uvoz ide na `POST /api/v1/{clients,suppliers,stock-items}/bulk`. Backend normalizira ("Njemačka"→"DE", "18,40"→18.40), preskače prazne redove.

## Struktura

```
backend/app/
  main.py            # FastAPI entry, servira i API i frontend
  config.py          # Pydantic Settings (čita .env)
  api/
    deps.py          # get_current_org_id (zamijeni kad bude auth)
    v1/
      router.py      # registrira sve rutere
      clients.py     # REAL CRUD + /bulk
      suppliers.py   # REAL CRUD + /bulk
      stock.py       # REAL CRUD + /bulk
      {auth,products,projects,documents,quotes}.py  # STUBOVI (TODO)
      health.py      # REAL
  db/
    session.py       # async engine (handluje i SQLite za testove)
    models/          # SQLAlchemy modeli (Org, User, Client, Supplier, StockItem, ...)
  schemas/           # Pydantic schemas (client.py, supplier.py, stock.py, ...)
  services/          # pricing (radi), tax (radi), llm, matching, ingestion (stubovi)
```

## Što JE gotovo

- CRUD + bulk import za clients, suppliers, stock-items (testirano, 15 testova prolazi)
- Frontend spojen na te endpointe s demo fallbackom (6 testova prolazi)
- Database shema (17 tablica + 2 view-a), seed podaci
- Pricing engine (landed cost + marža), tax engine (EU VAT 27 zemalja) — rade
- Docker setup koji bootash s `make up`

## Što NIJE gotovo (TODO, po prioritetu)

1. **Auth** — JWT login/registracija. Frontend login forma. Onda `get_current_org_id` čita org iz tokena.
2. **Document upload** — multipart endpoint koji prima PDF/XLSX, sprema u storage.
3. **Document parsing** — `app/services/ingestion/`: prvo pdfplumber/openpyxl (deterministički), pa LLM fallback (treba ANTHROPIC_API_KEY).
4. **Catalog matching** — `app/services/matching/`: 4-stage (exact SKU → fuzzy pg_trgm → embedding → LLM ranker).
5. **Quote builder backend** — trenutno samo frontend; treba endpointe za kreiranje/verzioniranje ponuda.

## Konvencije

- Async svugdje (async def, await db.execute).
- Pydantic v2: `model_config = ConfigDict(from_attributes=True)` na Response schemama.
- Formatiranje: `ruff format`. Lint: `ruff check`.
- Testovi: pytest, koristi SQLite in-memory za brze unit testove (vidi kako `db/session.py` handluje sqlite URL).
- NAPOMENA: backend je testiran sa SQLite jer dev sandbox nema Postgres. U produkciji je Postgres — kod je isti ali pazi na tipove (JSONB, UUID, pgvector ne postoje u SQLite).

## Workflow s tobom (Claude Code)

Prije nego mijenjaš kod: opiši pristup i čekaj moje odobrenje. Radi na malim, fokusiranim promjenama. Nakon svake gotove cjeline predloži git commit. Ako dodaješ endpoint, dodaj i test.
