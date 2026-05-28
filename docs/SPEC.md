# AI Quote & Procurement Platform — System Specification

**Verzija:** 1.0
**Domena:** Globalna B2B nabava i ponude (rasvjeta, elektro materijal, instalacije, projekti)
**Status:** Engineering blueprint, spreman za roadmap planiranje

---

## 0. TL;DR

Gradimo SaaS platformu koja od ulaznog dokumenta (PDF/XLSX troškovnik, RFQ, email s prilozima) producira strukturiranu, profitabilnu, klijent-spremnu ponudu — uz human-in-the-loop kontrolu, multi-currency / multi-tax podršku i mjerljiv win-rate model koji se s vremenom uči na vlastitim podacima.

Sustav nije monolitni "AI koji sve zna". To je deterministični pipeline (parsing → katalog match → kalkulacija → output) s LLM slojem na točno definiranim mjestima gdje deterministika ne radi (semantička klasifikacija, generiranje teksta, mapiranje "free-form" opisa na katalog).

Cilj prvih 6 mjeseci: jedan poslovni proces (RFQ → ponuda) automatiziran do 80%, mjerljiv ROI po obrađenom dokumentu. Sve ostalo (negotiation AI, market prediction, autonomous agents) gradi se tek nakon što imamo povijesne podatke koji takvu logiku mogu hraniti.

---

## 1. Što gradimo, a što NE gradimo (Anti-scope)

### Gradimo
- Ingestion pipeline za PDF, XLSX, CSV, DOCX, slike, email priloge
- Line-item extraction sa confidence scoreom i review UI-jem
- Master product catalog s mapiranjem na više dobavljača i povijesti cijena
- Quote engine s pravilima za marže, popuste, valutu, porez, Incoterms
- PDF/XLSX generator ponuda s brandingom i multi-language outputom
- Dashboard s win-rate, profit, pipeline metrikama
- Multi-tenant SaaS arhitektura (jedna instalacija, više tvrtki/timova)
- Audit log, role-based access, GDPR-compliant podaci

### Eksplicitno NE gradimo u prvoj godini
- "Market prediction engine" za buduće cijene komponenti — nemamo ulazni signal koji bi to hranio bez ozbiljnog data partnershipa
- Autonomous negotiation agente koji direktno komuniciraju s klijentima/dobavljačima — pravni i reputacijski rizik prevelik
- Vlastiti OCR/CV model — koristimo provjerene servise (Azure Document Intelligence, AWS Textract, Google Document AI) ili open-source (PaddleOCR, Tesseract) kao fallback
- Vlastiti LLM — koristimo Claude/GPT preko API-ja
- Replacment za računovodstvo — integriramo se s postojećim ERP/računovodstvenim sustavima, ne zamjenjujemo ih

Razlog za ovo razgraničenje: svaki sustav koji pokušava "biti sve" završi kao ništa. Fokusiramo se na RFQ-to-Quote workflow jer ondje je najveća ušteda vremena i najviše ponovljivosti.

---

## 2. Fazni roadmap

### Faza 0 — Foundation (tjedni 1–4)
Multi-tenant skeleton aplikacije: auth, organizacije, korisnici, role, file upload na object storage, osnovna baza, deploy pipeline, observability. Ništa od poslovne logike još.

**Deliverable:** Možeš se registrirati, kreirati organizaciju, pozvati kolegu, uploadati fajl, vidjeti ga u listi. Ništa pametnije od toga.

### Faza 1 — Document → Structured Data (tjedni 5–10)
Ingestion pipeline. Parsing PDF/XLSX troškovnika u strukturirane line iteme. Confidence scoring. Review UI gdje korisnik ispravlja krivu ekstrakciju. Svaki ispravak je trening signal za kasnije.

**Deliverable:** Uploadaš RFQ, dobiješ tablicu stavki koje možeš ispraviti i potvrditi. Bez katalog matchinga, bez cijena — samo čisti extraction.

### Faza 2 — Catalog & Item Matching (tjedni 11–16)
Master katalog proizvoda. Supplier mapping (jedan proizvod → više dobavljača s različitim cijenama, rokovima, MOQ). Fuzzy + semantic matching ekstrahiranih stavki na katalog. Manual override uvijek dostupan.

**Deliverable:** Ekstrahirane stavke se automatski mapiraju na artikle iz tvog kataloga, vidiš tko sve to prodaje i po kojoj cijeni.

### Faza 3 — Quote Generation (tjedni 17–22)
Pricing pravila (marže po kategoriji/klijentu/projektu), multi-currency s FX snapshotom u trenutku ponude, porez/PDV/GST po jurisdikciji, Incoterms, rokovi plaćanja. Quote builder UI. PDF/XLSX export s brandingom. Versioniranje ponuda. Approval workflow.

**Deliverable:** End-to-end: dokument unutra, ponuda van. Win-rate još nije mjeren jer nema povijesti.

### Faza 4 — Intelligence Layer (mjeseci 6–12)
Win/loss tracking. Pricing analytics. Supplier performance scoring. Klijentski profili. Dashboard s realnim metrikama. Prvi naivni win-rate model na povijesnim podacima.

**Deliverable:** Vidiš zašto dobivaš/gubiš poslove. Sustav počinje davati podatkom-utemeljene preporuke umjesto if/else heuristika.

### Faza 5 — Advanced (godina 2+)
Email asistent (draft pa human send). Multi-step agent za istraživanje dobavljača. Cost prediction modeli kad imaš dovoljno povijesnih podataka. Integracije s ERP/računovodstvom (QuickBooks, Xero, Sage, SAP Business One, Pantheon, Minimax).

Ovo nije roadmap koji se obećava klijentu — ovo je interni redoslijed gradnje. Svaka faza isporučuje stvarnu vrijednost samostalno.

---

## 3. Domenski model — entiteti i odnosi

Prije sheme baze, razmišljanje o domeni.

**Organization** je tvrtka koja koristi sustav (multi-tenant root). Svaka organizacija ima svoje korisnike, svoj katalog, svoje klijente, svoje dobavljače, svoje ponude. Podaci između organizacija su strogo izolirani.

**User** pripada jednoj ili više organizacija s različitim rolama (admin, sales, procurement, viewer, approver).

**Client** je kupac kojem nudimo. **Contact** je osoba kod klijenta. Klijent ima `client_profile` s podacima poput tipičnog budžeta, preferiranih brendova, povijesti plaćanja, regije.

**Supplier** je dobavljač od kojeg kupujemo. Supplier ima rating, payment terms, lead time pattern, povijest pouzdanosti.

**Product** je kanonski artikl u našem katalogu (npr. "LED panel 60x60 4000K 36W UGR<19"). **SupplierProduct** je veza između našeg kanonskog proizvoda i konkretne ponude jednog dobavljača (njegova šifra, cijena, MOQ, lead time). Jedan Product može imati N SupplierProduct mapiranja. Ovo je ključna apstrakcija — bez nje ne možeš usporedjivati dobavljače.

**Project** je krovni entitet za jedan posao/RFQ. Ima tip, status, klijenta, vrijednost, deadline.

**Document** je svaki uploadani fajl. **DocumentExtraction** je rezultat parsiranja — strukturirane stavke s confidence scoreom.

**Quote** je jedna verzija ponude na project. Project može imati više Quote verzija (V1, V2 nakon pregovaranja). Quote ima **QuoteLineItem**-e, svaki s referencom na Product, SupplierProduct (odakle uzimamo), našom prodajnom cijenom, maržom.

**QuoteOutcome** se bilježi nakon što je ponuda riješena (won/lost/withdrawn/expired) — s razlogom, finalnom cijenom konkurencije ako znamo, lessons learned.

**FxRate** snapshot tečaja u trenutku ponude (NIKAD ne računaj s live tečajem retroaktivno).

**TaxRule** definira porez po jurisdikciji i tipu transakcije (B2B EU reverse charge, US sales tax po stateu, UK VAT, itd).

**AuditLog** bilježi tko je što radio kad. Imutabilan, append-only.

Ovo je 14 glavnih entiteta. Sve ostalo (notifications, comments, attachments) su pomoćne tablice oko njih.

---

## 4. Tehnička arhitektura

### 4.1 Tech stack — jedan jasan izbor s razlogom

**Frontend:** Next.js 14+ (App Router), TypeScript strict mode, Tailwind CSS, shadcn/ui za komponente, TanStack Query za server state, Zustand za client state, React Hook Form + Zod za forme.

*Zašto:* Next.js je danas defacto standard za React SaaS, daje server-side rendering za marketing/landing, RSC za dashboard, dobre developer ergonomije. shadcn/ui umjesto Material/Ant jer ne želimo "AI generic" izgled.

**Backend:** Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic migracije, Pydantic v2.

*Zašto Python, ne Node?* Cijeli AI/ML ekosustav je Python-native (pandas, openpyxl, pdfplumber, langchain, instructor, dspy). Multi-language backend je premium za malu ekipu. Drži se jednog. FastAPI je dovoljno brz za 99% realnih slučajeva.

**Async job runner:** Celery + Redis (ili Dramatiq ako želiš modernije). Document processing, OCR, LLM pozivi — sve ide async. Sinkroni HTTP request samo za "enqueue job + return job_id".

**Baza:** PostgreSQL 16 s ekstenzijama: `pgvector` (embeddings, RAG), `pg_trgm` (fuzzy matching), `tsvector` (full-text search), `pg_partman` (particioniranje audit_loga).

*Zašto ne Elasticsearch + Vector DB + Postgres?* Jer Postgres s ovim ekstenzijama pokriva sve do otprilike 10-50M dokumenata bez problema. Manji ops overhead, jedna baza za backup, manje tooling skill seta. Elasticsearch i dedicated vector DB (Pinecone, Weaviate, Qdrant) dodaješ kad ti je Postgres usko grlo, ne prije.

**Object storage:** S3 ili S3-kompatibilan (AWS S3, Cloudflare R2 za jeftin egress, MinIO za self-hosted). Dokumenti, generirani PDF-ovi, slike.

**Cache:** Redis. Sessions, rate limiting, query cache, queue broker.

**Auth:** Clerk ili Auth0 za prvih X tisuća korisnika (brzo, sigurno, multi-tenant out of the box). Self-hosted Keycloak ako klijenti to traže enterprise.

**LLM:** Claude (Sonnet za rutinske zadatke, Opus za kompleksno reasoniranje) kao primarni. GPT-4 klasa kao fallback. Apstrahirano kroz vlastiti `LLMProvider` interface da možeš mijenjati. Lokalni open-source model (Llama 3.x, Qwen) za zadatke gdje privatnost ili trošak diktiraju.

**OCR / Document AI:** Hibrid. Prvo pokušaj `pdfplumber` + `camelot` za tekstualne PDF-ove (besplatno, brzo, deterministično). Fallback na Azure Document Intelligence ili AWS Textract za skenirane/složene dokumente. PaddleOCR kao open-source backup.

**Embeddings:** OpenAI `text-embedding-3-small` ili `voyage-multilingual-2` (bolji za ne-engleske jezike). Spremati u pgvector.

**Observability:** OpenTelemetry → Grafana/Loki/Tempo stack (self-hosted), ili Datadog/Honeycomb (managed). Sentry za frontend errore.

**Deployment:** Docker Compose za development. Za produkciju u ranoj fazi: Railway, Fly.io ili Render — manje DevOps overhead nego K8s. Kasnije AWS/GCP s ECS ili EKS ako scale to traži.

**CI/CD:** GitHub Actions. Pre-commit hookovi za lint/format/types. Konvencionalni commitovi.

### 4.2 Deployment topologija (high level)

```
                       ┌─────────────────┐
                       │   Cloudflare    │
                       │  (CDN + WAF)    │
                       └────────┬────────┘
                                │
                ┌───────────────┴───────────────┐
                │                               │
        ┌───────▼────────┐             ┌───────▼────────┐
        │  Next.js App   │             │  FastAPI       │
        │  (Vercel/      │             │  (Container)   │
        │   container)   │             │                │
        └────────────────┘             └───────┬────────┘
                                                │
                ┌───────────────┬───────────────┼───────────────┬──────────────┐
                │               │               │               │              │
        ┌───────▼────────┐ ┌────▼─────┐ ┌──────▼──────┐ ┌──────▼──────┐ ┌────▼─────┐
        │  PostgreSQL    │ │  Redis   │ │   S3/R2     │ │  Celery     │ │  LLM API │
        │  + pgvector    │ │          │ │  (storage)  │ │  workers    │ │  (Claude)│
        └────────────────┘ └──────────┘ └─────────────┘ └─────────────┘ └──────────┘
```

Sve iza Cloudflarea (DDoS, WAF, rate limiting). App i API u kontejnerima, horizontalno skalabilni. Postgres s read replikama tek kad zatreba. Workeri odvojeni od web procesa jer LLM/OCR pozivi mogu biti dugi.

---

## 5. Database schema (skraćeno, ali realno)

Ovo nije ER dijagram pun-prsten-pun-prsten, ovo je SQL skica koju developer može uzeti i nastaviti.

```sql
-- Multi-tenancy & users
CREATE TABLE organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    slug            TEXT UNIQUE NOT NULL,
    country_code    CHAR(2) NOT NULL,           -- ISO 3166-1 alpha-2
    base_currency   CHAR(3) NOT NULL,           -- ISO 4217 (EUR, USD, GBP, ...)
    locale          TEXT NOT NULL DEFAULT 'en', -- BCP 47 (hr-HR, en-US, ...)
    timezone        TEXT NOT NULL DEFAULT 'UTC',-- IANA tz (Europe/Zagreb)
    settings        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           CITEXT UNIQUE NOT NULL,
    full_name       TEXT NOT NULL,
    auth_provider   TEXT,           -- 'clerk', 'auth0', 'local'
    auth_subject    TEXT,           -- external ID
    locale          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
    org_id          UUID REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('owner','admin','sales','procurement','viewer','approver')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);

-- Clients
CREATE TABLE clients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    legal_name      TEXT,
    tax_id          TEXT,                       -- VAT number, EIN, etc.
    country_code    CHAR(2) NOT NULL,
    industry        TEXT,
    segment         TEXT,                       -- 'hotel','retail','industrial','public','residential'
    payment_terms_days INT DEFAULT 30,
    credit_limit    NUMERIC(14,2),
    risk_score      NUMERIC(3,2),               -- 0..1
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, tax_id)
);

CREATE TABLE contacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    full_name       TEXT NOT NULL,
    email           CITEXT,
    phone           TEXT,
    role            TEXT,
    is_primary      BOOLEAN DEFAULT FALSE
);

-- Suppliers
CREATE TABLE suppliers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    country_code    CHAR(2) NOT NULL,
    currency        CHAR(3) NOT NULL,
    incoterms_default TEXT,                     -- 'EXW','FCA','DAP','DDP', ...
    lead_time_days_avg INT,
    rating          NUMERIC(3,2),
    on_time_rate    NUMERIC(3,2),
    quality_score   NUMERIC(3,2),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Product catalog (canonical)
CREATE TABLE products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    sku             TEXT NOT NULL,              -- our internal SKU
    name            TEXT NOT NULL,
    description     TEXT,
    category        TEXT,                       -- 'led_panel','spotlight','cable','breaker', ...
    brand           TEXT,
    specs           JSONB,                      -- {wattage:36, lumen:3600, cct:4000, ip:20, ...}
    unit            TEXT NOT NULL DEFAULT 'pcs',-- 'pcs','m','kg','set', ...
    embedding       VECTOR(1536),               -- for semantic matching
    search_text     tsvector,                   -- for FTS
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, sku)
);

CREATE INDEX products_embedding_idx ON products USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX products_search_idx ON products USING gin (search_text);
CREATE INDEX products_trgm_idx ON products USING gin (name gin_trgm_ops);

-- Supplier-product mapping (THIS is what makes multi-supplier comparison possible)
CREATE TABLE supplier_products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    supplier_id     UUID NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    supplier_sku    TEXT,
    supplier_name   TEXT,                       -- how supplier calls it
    moq             INT DEFAULT 1,
    pack_size       INT DEFAULT 1,
    lead_time_days  INT,
    is_active       BOOLEAN DEFAULT TRUE,
    UNIQUE (product_id, supplier_id)
);

-- Price history (never overwrite, always insert)
CREATE TABLE supplier_price_history (
    id              BIGSERIAL PRIMARY KEY,
    supplier_product_id UUID NOT NULL REFERENCES supplier_products(id) ON DELETE CASCADE,
    unit_price      NUMERIC(14,4) NOT NULL,
    currency        CHAR(3) NOT NULL,
    valid_from      TIMESTAMPTZ NOT NULL,
    valid_to        TIMESTAMPTZ,
    source          TEXT,                       -- 'manual','catalog_import','quote_extracted'
    notes           TEXT
);

-- FX rates snapshot
CREATE TABLE fx_rates (
    base_ccy        CHAR(3) NOT NULL,
    quote_ccy       CHAR(3) NOT NULL,
    rate            NUMERIC(18,8) NOT NULL,
    source          TEXT NOT NULL,              -- 'ecb','openexchangerates','manual'
    as_of           TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (base_ccy, quote_ccy, as_of)
);

-- Tax rules (pluggable per jurisdiction)
CREATE TABLE tax_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID REFERENCES organizations(id),
    country_code    CHAR(2) NOT NULL,
    region          TEXT,                       -- US state, etc.
    rule_type       TEXT NOT NULL,              -- 'vat','sales_tax','gst','reverse_charge','zero_rated'
    rate            NUMERIC(5,4),
    applies_when    JSONB,                      -- conditions
    valid_from      DATE NOT NULL,
    valid_to        DATE
);

-- Projects (umbrella for a deal)
CREATE TABLE projects (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    client_id       UUID REFERENCES clients(id),
    name            TEXT NOT NULL,
    project_type    TEXT,                       -- 'hotel','office','residential','industrial','public_lighting','retail'
    status          TEXT NOT NULL DEFAULT 'draft',
                    -- 'draft','quoting','submitted','won','lost','withdrawn','on_hold'
    estimated_value NUMERIC(14,2),
    estimated_value_ccy CHAR(3),
    deadline_at     TIMESTAMPTZ,
    site_country    CHAR(2),
    site_region     TEXT,
    urgency         TEXT,                       -- 'normal','urgent','critical'
    assigned_to     UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Documents
CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id      UUID REFERENCES projects(id) ON DELETE SET NULL,
    uploaded_by     UUID REFERENCES users(id),
    storage_key     TEXT NOT NULL,              -- S3 key
    filename        TEXT NOT NULL,
    mime_type       TEXT,
    size_bytes      BIGINT,
    checksum        TEXT,
    source          TEXT,                       -- 'upload','email','api','drive'
    detected_lang   TEXT,
    status          TEXT NOT NULL DEFAULT 'received',
                    -- 'received','parsing','parsed','failed','reviewed'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE document_extractions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    raw_text        TEXT,                       -- full text from OCR/parse
    structured_data JSONB,                      -- {line_items: [...], header: {...}}
    extraction_method TEXT,                     -- 'pdfplumber','azure_di','textract','llm'
    confidence      NUMERIC(3,2),
    needs_review    BOOLEAN DEFAULT TRUE,
    reviewed_by     UUID REFERENCES users(id),
    reviewed_at     TIMESTAMPTZ
);

-- Quotes
CREATE TABLE quotes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version         INT NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'draft',
                    -- 'draft','review','approved','sent','accepted','rejected','expired'
    currency        CHAR(3) NOT NULL,
    fx_snapshot     JSONB,                      -- rates used at quote time
    subtotal        NUMERIC(14,2),
    discount_total  NUMERIC(14,2) DEFAULT 0,
    tax_total       NUMERIC(14,2),
    total           NUMERIC(14,2),
    cost_total      NUMERIC(14,2),              -- our COGS
    margin_pct      NUMERIC(5,4),
    valid_until     DATE,
    payment_terms   TEXT,
    incoterms       TEXT,
    delivery_terms  TEXT,
    notes_internal  TEXT,
    notes_external  TEXT,
    created_by      UUID REFERENCES users(id),
    approved_by     UUID REFERENCES users(id),
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, version)
);

CREATE TABLE quote_line_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quote_id        UUID NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    position        INT NOT NULL,
    product_id      UUID REFERENCES products(id),
    supplier_product_id UUID REFERENCES supplier_products(id),
    description     TEXT NOT NULL,
    quantity        NUMERIC(14,4) NOT NULL,
    unit            TEXT NOT NULL,
    unit_cost       NUMERIC(14,4),              -- what we pay supplier (in quote currency)
    unit_price      NUMERIC(14,4) NOT NULL,     -- what client pays
    discount_pct    NUMERIC(5,4) DEFAULT 0,
    tax_rate        NUMERIC(5,4),
    line_total      NUMERIC(14,2),
    margin_pct      NUMERIC(5,4),
    notes           TEXT
);

CREATE TABLE quote_outcomes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quote_id        UUID NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    outcome         TEXT NOT NULL,              -- 'won','lost','withdrawn','expired','no_response'
    reason          TEXT,                       -- 'price','delivery','quality','relationship','other'
    competitor_name TEXT,
    competitor_price NUMERIC(14,2),
    lessons         TEXT,
    recorded_by     UUID REFERENCES users(id),
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Audit log (append-only)
CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    org_id          UUID NOT NULL,
    user_id         UUID,
    action          TEXT NOT NULL,              -- 'quote.created','document.uploaded',...
    entity_type     TEXT,
    entity_id       UUID,
    before_state    JSONB,
    after_state     JSONB,
    ip_address      INET,
    user_agent      TEXT,
    at              TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (at);
```

Ovo je 95% sheme. Nedostaju samo neke pomoćne tablice (notifikacije, komentari, attachmenti na ponudu). Bitno je da je struktura ispravna: **multi-tenant je u svakoj tablici izoliran preko `org_id`**, **cijene i tečajevi se ne prepisuju nego dodaju**, **ponude su versionirane**, **audit log je particioniran**.

Row-Level Security (RLS) na Postgresu omogućava da na razini baze garantiramo izolaciju između tenanta — kritično za sigurnost.

---

## 6. Document Ingestion Pipeline — korak po korak

Ovo je srce sustava i mjesto gdje se najviše greši ako se napravi naivno.

### Korak 1: Upload i klasifikacija
Datoteka stiže (UI upload, email, API, Drive sync). Spremi u object storage. Izračunaj checksum (deduplikacija). Detektiraj MIME, jezik (prvih X tisuća znakova kroz fastText ili LLM mini-classifier), tip dokumenta (RFQ, troškovnik, katalog, drugo). Enqueue job.

### Korak 2: Routing prema parseru
Ne radi sve kroz LLM, to je rasipanje.

- **PDF s tekstom (native)** → `pdfplumber` + `camelot` za tablice. Brzo, deterministično, besplatno.
- **PDF skeniran (slike)** → Azure Document Intelligence (najbolji za troškovnike i tablice) ili AWS Textract. Fallback PaddleOCR.
- **XLSX/XLS** → `openpyxl` + heuristike za detekciju header retka i podatkovnog područja (header nije uvijek u prvom retku, troškovnici znaju imati logo, naslove, prazne retke).
- **DOCX** → `python-docx` za tekst + tablice.
- **CSV** → `pandas` s autodetekcijom separatora i encodinga (`chardet`).
- **Slika** → isto kao PDF skeniran.
- **Email body** → `mailparse` + tretiraj kao tekst, prilozi idu kroz pripadajuće parsere.

### Korak 3: Strukturirani extraction
Iz raw outputa parsera dobiješ tablice/redove. Sada treba prepoznati line iteme.

**Naivni pristup (radi za 60% slučajeva):** ako tablica ima jasne kolone "opis/količina/jedinica/cijena", direktno mapiraj.

**Realni pristup:** prosljedi tablice + meta kontekst LLM-u s strukturiranim outputom (Pydantic schema preko `instructor` ili native JSON mode):

```python
class LineItem(BaseModel):
    position: int | None
    description: str
    quantity: Decimal
    unit: str  # normalized to 'pcs','m','kg','set','m2','m3','box','lot'
    unit_price: Decimal | None
    currency: str | None  # ISO 4217
    notes: str | None
    confidence: float  # 0..1

class ExtractedDocument(BaseModel):
    document_type: Literal['rfq','quote','price_list','invoice','other']
    client_name: str | None
    client_tax_id: str | None
    project_name: str | None
    deadline: date | None
    currency: str | None
    language: str
    line_items: list[LineItem]
    requirements: list[str]  # free-text requirements (warranty, delivery, certifications)
    confidence: float
```

LLM ovdje ne računa ništa — samo strukturira ono što već postoji u dokumentu. To je sigurno korištenje (low hallucination risk).

### Korak 4: Confidence scoring i routing na review
Svaki line item dobiva confidence. Logika:
- Numerički podaci parsirani izravno iz strukturirane ćelije → 0.95+
- LLM extraction iz polustrukturirane tablice → 0.7–0.9
- OCR + LLM iz skenirane slike → 0.5–0.8
- Ako confidence < 0.85 ili je suma redova ne odgovara totalu dokumenta → flag `needs_review=true`

### Korak 5: Review UI
Operater vidi originalni dokument lijevo, ekstrahirane stavke desno, klikom na stavku označava područje u originalu (bounding box). Može ispraviti, dodati, obrisati red. Svaki ispravak se loguje kao trening signal za fine-tune kasnije.

**Pravilo:** ponuda NIKAD ne ide klijentu prije review-a, ma kolika confidence bila. U enterprise B2B kontekstu, jedna pogrešno parsirana nula u količini = katastrofa.

### Korak 6: Normalizacija
Jedinice mjere: "kom", "pc", "Stk", "штук" → `pcs`. "metar", "m", "mtr" → `m`. Pravi lookup tablicu, ne if/else.

Valute: prepoznaj iz simbola, koda, konteksta. Ako ambiguous (npr. "$" može biti USD, CAD, AUD), pitaj korisnika.

Brojevi: "1.234,56" (EU) vs "1,234.56" (US) — detektiraj iz lokacije dokumenta + heuristike.

### Korak 7: Spremi i nastavi
Strukturirani podaci u `document_extractions.structured_data`. Status `parsed`. Trigger sljedeći korak: katalog matching.

---

## 7. Catalog Matching — najteži problem

Imaš line item: `"LED panel 595x595 36W 4000K UGR<19 IP20"`. Tvoj katalog ima 50.000 artikala. Treba naći onaj koji odgovara — ili konstatirati da ne postoji.

### Pristup u 3 nivoa

**Nivo 1: Exact SKU match.** Ako dokument sadrži tvoj SKU ili poznati supplier SKU → direct hit.

**Nivo 2: Fuzzy + Full-text.** Postgres `pg_trgm` similarity + `tsvector` FTS. Brzo, besplatno, dobro za "skoro točne" matchove. Top-N kandidati za nivo 3.

**Nivo 3: Semantic embedding match.** Embedding na opis line itema, cosine similarity nad embeddinzima kataloga (pgvector). Top-N preklopni s nivoom 2.

**Nivo 4 (samo ako 1-3 ambiguous): LLM ranker.** Daj LLM-u opis line itema + top-10 kandidata, traži ga da rangira i da confidence. NE traži ga da "izmisli" match — samo da odabere ili kaže "ništa ne odgovara".

### Specs validation
Nakon što imamo kandidata, **uvijek** provjeri specs deterministički:
- Snaga (W), CCT (K), IP rating, dimenzije, napon
- Ako specs iz dokumenta proturječe specs kandidata → odbij match, flag za ručno

### Što kad nema matcha
Tri opcije korisniku:
1. Kreiraj novi proizvod u katalogu iz ove stavke
2. Mapiraj na postojeći proizvod ručno
3. Označi kao "non-catalog item" — ide u ponudu ali bez supplier matchinga

Sve tri opcije postaju trening signal: što je operater odabrao za buduće slične stavke.

### Multi-supplier comparison
Kad imamo Product match, automatski povučemo sve aktivne `supplier_products` za taj proizvod. Tablica koju operater vidi:

```
Supplier      Unit Cost   Currency  Lead   MOQ   Rating   Score
SupplierA     12.40       EUR       7d     10    4.5      ★★★★★
SupplierB     11.80       EUR       14d    50    4.2      ★★★★
SupplierC     14.00       USD→13.0  3d     1     4.8      ★★★★★
```

Score je sažeti index (cijena × pouzdanost × lead time × MOQ pogodnost). Nije magija, nego transparentna formula koju korisnik može namjestiti per organizacija.

---

## 8. Pricing, Margin & Quote Engine

### 8.1 Pricing pravila — rule-based prvo, ML kasnije

**Cijenu odluci kroz pipeline pravila s prioritetom:**

1. Eksplicitno postavljena cijena na quote line item (manual override) — wins
2. Klijent-specifična cijena (negotiated price list per client)
3. Volume tier (npr. > 100 kom = drukčija marža)
4. Kategorijska marža (LED panels = 18%, kablovi = 8%, instalacijski rad = 35%)
5. Default org margin

Svako pravilo loguje **zašto** je primijenjeno (vidljivo u UI: "Cijena izračunata iz: Client tier B + Category margin LED panel 18%"). Transparentnost je važnija od pametne magije.

### 8.2 Realna profit formula (ne ona iz originala)

```
Unit Margin Amount  = Unit Sell Price − Unit Landed Cost
Unit Landed Cost    = Supplier Unit Price (in quote ccy)
                    + Allocated Logistics
                    + Allocated Duties/Customs
                    + Allocated Handling
                    + FX Conversion Cost
                    + Payment Term Cost  (DSO − DPO) × cost_of_capital
                    + Risk Reserve       (warranty, returns, defect rate)

Gross Margin %      = Unit Margin Amount / Unit Sell Price
Quote Total Margin  = Σ (line margin × quantity) − fixed project costs

Effective Margin    = Quote Total Margin − expected discount in negotiation
```

Cost of capital je realna stvar. Ako klijent plaća 90 dana a dobavljač traži 30, vežeš kapital 60 dana — to nije besplatno.

### 8.3 Multi-currency

Svaka ponuda ima svoju `currency` i `fx_snapshot` u trenutku kreiranja. FX rates dolaze iz pouzdanog izvora (ECB, OpenExchangeRates, ili banka klijenta).

**Pravilo:** kad supplier cost dolazi u drugoj valuti od quote currency, konvertiraj **u trenutku kalkulacije** i spremi i original i konvertirani iznos. Nikad ne retroaktivno preračunavaj.

### 8.4 Multi-tax — globalna pluginska struktura

Porez nije "PDV 25%". Porez je matrica jurisdikcije × tip transakcije × tip robe × status kupca. Primjeri:

- **EU B2B intra-community** s validnim VAT ID-em → reverse charge (0% na fakturi, primalac obračunava)
- **EU B2C** → VAT zemlje kupca preko OSS sheme (e-commerce iznad praga)
- **EU B2B domestic** → standardni VAT
- **US** → sales tax, varira po stateu, nekima po countiju; nexus pravila
- **UK** → VAT, post-Brexit pravila za EU
- **GCC** → VAT (UAE, SA), neki proizvodi izuzeti
- **CH/NO** → vlastiti VAT režimi
- **Export izvan jurisdikcije** → zero-rated, ali treba dokumentacija

Implementacija: `TaxRule` tablica + pluginski engine `TaxEngine.calculate(line_item, seller, buyer, transaction_type) -> TaxResult`. Početno hardkodirana pravila za 5-10 ključnih jurisdikcija. Kasnije: integracija s TaxJar, Avalara ili Stripe Tax za kompleksne slučajeve.

### 8.5 E-invoicing po regijama (samo lista, ne implementacija sad)

Spomenuti u arhitekturi jer će klijenti tražiti:
- Croatia: eRačun (Fina) — obavezno B2G, B2B u tijeku
- Italy: SDI (FatturaPA)
- France: Factur-X / Chorus Pro
- Spain: Facturae
- Germany: XRechnung / ZUGFeRD
- Poland: KSeF
- Latin America: razne (Mexico CFDI, Brazil NFe...)
- Saudi Arabia: ZATCA Fatoora

Output ponude treba biti strukturiran tako da se kasnije može mapirati na bilo koji od ovih formata. Ne implementirati sve odjednom — kreni s 1-2 ključne jurisdikcije po potražnji.

### 8.6 Quote PDF generator
Koristi WeasyPrint ili Playwright (HTML→PDF). Templates u Jinja2 ili React (server-side render). Multi-language podrška na razini templatea. Branding (logo, boje, fontovi) per organization.

---

## 9. AI / LLM Layer — gdje i kako koristimo

Ovo je sekcija gdje sam najtvrđi prema originalu jer "AI će to riješiti" je antipattern.

### Gdje LLM stvarno pomaže

1. **Document understanding** — strukturiranje neuredne tablice u JSON
2. **Item matching ranker** — disambiguacija kad fuzzy + embedding daju ambiguous rezultate
3. **Tekst ponude i opisa** — generiranje technical descriptiona i sales copy na više jezika
4. **Email drafting** — predložak follow-up emaila kojeg korisnik pregleda i pošalje
5. **Summarization** — sažeci kompleksnih RFQ-ova ("što ovaj klijent zapravo traži")
6. **Q&A nad povijesnim ponudama** — RAG nad bazom prošlih ponuda ("daj mi sve hotelske projekte u Hrvatskoj iznad 100k EUR i njihove marže")
7. **Anomaly detection narrative** — kad detekcijska heuristika nađe anomaliju (cijena izvan 3σ od povijesnog prosjeka), LLM piše ljudski objašnjivi razlog

### Gdje LLM NE TREBA — koristi deterministični kod

- Matematika (sume, marže, FX) — NIKAD LLM
- Business rules (kad primijeniti popust) — pravila, ne LLM
- Database queries — ORM, ne LLM koji generira SQL u produkciji
- Authorization — kod, ne "AI agent koji procjenjuje ima li korisnik pristup"
- Approval workflows — state machine, ne LLM
- Final pricing odluka — pravila + ručno odobrenje, LLM može predlagati

### LLM patterns koje koristimo

- **Structured output (instructor/Pydantic)** — uvijek tražimo JSON s validacijom, nikad slobodni tekst za podatke
- **Tool use / function calling** — LLM bira između dobro definiranog skupa funkcija (`search_catalog`, `get_supplier_price`, `calculate_margin`), ne piše proizvoljni kod
- **RAG** — kontekst iz embeddinga povijesnih ponuda i kataloga, nikad LLM koji "pamti" iz treninga
- **Few-shot examples** — prompt uvijek sadrži 3-5 primjera dobre i loše ekstrakcije iz dokumenata
- **Eval suite** — bench skup od 100+ stvarnih dokumenata s ground truth ekstraktima; svaki promp change se testira

### LLM provider apstrakcija

```python
class LLMProvider(Protocol):
    async def complete(self, messages, schema=None, tools=None, **kwargs) -> Response: ...

class ClaudeProvider(LLMProvider): ...
class OpenAIProvider(LLMProvider): ...
class LocalLlamaProvider(LLMProvider): ...
```

Switch providera bez koda. Bitno za vendor risk, troškovne arbitraže, privatnost.

---

## 10. Master Prompt za Quote Agent (realna verzija)

Ovo je verzija prompta koja je *zapravo izvediva*, za razliku od originalnog "ti si svemoćni AI".

```
ROLE
You are a procurement and quoting assistant for a B2B trading and project
company. You operate in a multi-tenant SaaS system. You have access to:
- The organization's product catalog (via search_catalog tool)
- Active supplier price lists (via get_supplier_prices tool)
- Historical quotes for this client (via search_quote_history tool)
- FX rates (via get_fx_rate tool)
- Tax rules for the relevant jurisdiction (via get_tax_rule tool)

You DO NOT calculate financial totals yourself. You DO NOT decide final
prices. You propose, the deterministic pricing engine computes, a human
approves.

PRIMARY TASKS
Given an extracted RFQ document with line items, you:
1. For each line item, propose the best matching catalog product(s) with
   confidence. If multiple candidates exist, rank them and explain why.
2. For each matched product, propose which supplier offering to use,
   considering price, lead time, MOQ, reliability, and project deadline.
   Output your reasoning briefly per choice.
3. Identify line items that are NOT in catalog and propose either creating
   them or substituting with a near-equivalent (must call out the
   substitution explicitly).
4. Flag anomalies: quantities that look like typos (1000x more than typical),
   specs that contradict (e.g. IP20 panel for outdoor use), missing critical
   info (no quantity, no unit, no deadline).
5. Summarize the RFQ in 3-5 bullet points for the salesperson.

CONSTRAINTS
- Never invent SKUs, prices, or supplier names. If you don't know, say so.
- Never compute totals — that's the pricing engine's job.
- Never approve, send, or commit anything — you're advisory.
- Always output structured JSON matching the provided schema.
- If a field is uncertain, mark confidence < 0.8 and add a note.
- Respond in the language of the source document for free-text fields,
  unless instructed otherwise.
- All monetary amounts you mention include explicit currency code.

OUT OF SCOPE — refuse politely if asked
- Negotiating directly with clients or suppliers
- Making final pricing decisions
- Approving or sending quotes
- Speculating about future market prices without data backing
- Legal or tax advice beyond applying provided tax rules

OUTPUT
Always return JSON conforming to the AgentResponse schema. Free-form text
goes into designated `reasoning` and `notes` fields. No prose outside JSON.
```

Ovo je prompt koji ima granice. Nema "razmišljaj kao CFO + senior sales + data scientist" — to su prazne riječi. Umjesto toga: jasna rola, jasni alati, jasne zabrane, strukturirani output.

---

## 11. Human-in-the-loop & Approval Workflow

Ovo je sekcija koja je u originalu praktički nedostajala, a kritična je.

### State machine za quote

```
draft → review_requested → approved → sent → (accepted|rejected|expired)
              ↓
          revisions_needed → draft
```

### Approval matrica (default, konfigurabilna po org)

- Quote value < 5.000 EUR → sales rep može slati direktno
- 5.000 – 50.000 EUR → potreban approver (sales manager)
- > 50.000 EUR ili margin < 5% → potreban dual approval (sales manager + CFO/owner)
- Bilo koji quote s AI confidence < 0.85 na bilo kojoj liniji → ručni review obavezan
- Bilo koji non-catalog item → ručni review obavezan

### Što review znači u praksi

Reviewer u UI-ju vidi:
- Original dokument klijenta
- Ekstrahirane stavke s confidence per stavka
- Predloženo katalog mapiranje
- Predloženi supplier i cijena
- Naša marža po stavci i ukupno
- Što AI agent kaže (reasoning, anomalije, preporuke)
- Povijest ponuda istom klijentu (winrate, prosječna marža)

Može: odobriti, izmijeniti pa odobriti, vratiti na doradu, odbiti.

Svaka akcija ide u audit log.

---

## 12. Win-Rate i Learning Loop (poštena verzija)

### Cold start problem
Prvih 6-12 mjeseci sustav nema dovoljno povijesnih podataka da bi "ML predviđao win rate". To je realnost. Rješenje: rule-based heuristike + ručno označavanje + skupljanje podataka.

### Što bilježimo (od dana 1)
Za svaki quote, u trenutku slanja:
- Sve features quotea: ukupni iznos, margin, broj stavki, currency, dani do deadlinea, client segment, project type, has competitor (yes/no), competitor known names, season, lead time...
- Sve features klijenta: industry, country, prijašnji win-rate s njima, payment history score
- Sve features konteksta: koji sales rep, kolika je ponuda relativna na klijentovo povijesno spending

### Outcome tracking
Svaki quote dobiva outcome (won/lost/expired/no_response) s razlogom. Ovo je obavezno polje — bez outcome unosa, ne možeš zatvoriti project status. Force discipline.

### Faza 4 ML model
Kad imaš ~500+ završenih quotea, treniraš jednostavan model (logistic regression ili gradient boosted trees, NE deep learning) na win/loss outcomeu. Outputi:
- Predicted win probability za novi quote
- Feature importance (što najviše utječe na win rate u tvojoj firmi)
- Recommended margin range koja maksimizira expected value (P(win) × margin)

Ovo je honest ML — interpretable, audit-friendly, ne čarobno.

### Ne radimo
- "Real-time market prediction" — nemamo signal
- "AI predviđa cijenu konkurencije" — nemamo podatke konkurencije osim onih koje sami unesemo u quote_outcomes
- Deep learning na 500 redova — overfitting garantirano

---

## 13. Security, Compliance, Audit

### Authentication
- OAuth 2.0 / OIDC via Clerk/Auth0
- MFA obavezno za admin role
- SSO (SAML) za enterprise klijente
- Session timeout konfigurabilan (default 8h aktivne, 30 dana refresh)

### Authorization
- RBAC s rolama (owner/admin/sales/procurement/viewer/approver)
- Resource-level permissions gdje treba (npr. sales rep vidi samo svoje klijente)
- Postgres Row-Level Security kao defense-in-depth

### Data at rest
- Postgres: enkripcija na storage levelu (cloud provider managed keys ili customer-managed via KMS)
- Object storage: server-side encryption, signed URLs s expiration za pristup
- Sekrcrets: AWS Secrets Manager / HashiCorp Vault, nikad u env varijablama u Gitu

### Data in transit
- TLS 1.3 svuda
- Certificate pinning za mobile app (kad/ako stigne)
- mTLS između internih servisa u produkciji

### GDPR / Privacy
- Data Processing Agreement template
- Right to access, rectify, delete na razini API endpointa
- Pseudonymizacija u audit logu nakon X dana (zadržati event ali ne PII)
- Data retention policy konfigurabilna per org
- DPIA dokumentacija
- AI subprocessors listed (Anthropic, OpenAI, Azure, AWS) — bitno za enterprise klijente

### Audit
- Append-only audit_log particiniran po mjesecima
- Critical actions: quote.sent, quote.approved, supplier.created, price.changed, user.role_changed, document.deleted
- Export audit log u SIEM (Splunk, Datadog) za enterprise

### LLM security
- PII redaction prije slanja u LLM (ako klijent traži zero-trust prema providers)
- Prompt injection defense: validacija LLM output strukture, nikad ne izvršavaj sirovi LLM output kao kod/SQL
- Rate limiting po user/org za LLM pozive (cost protection)

### Compliance roadmap
- SOC 2 Type I → Type II (kad bude smisla, ~ 18 mjeseci u)
- ISO 27001 za EU enterprise
- HIPAA NE relevantno (osim ako idemo u healthcare lighting što nije plan)

---

## 14. Observability i Operations

### Logs
Strukturirani JSON logs preko `structlog`. Trace ID kroz request → worker → LLM call. Loki ili Datadog za query.

### Metrics
Prometheus-compatible metrics:
- HTTP request rate / latency / error rate (RED)
- Worker queue depth, job duration percentiles
- LLM call count / latency / token usage / cost per org
- Document parsing success rate per parser
- Quote conversion funnel: uploaded → parsed → reviewed → quoted → sent → won

### Tracing
OpenTelemetry s sampling. Trace pojedinog document processinga end-to-end (upload → parse → match → quote).

### Alerts
- Worker queue depth > threshold (something stuck)
- LLM error rate > 5% (provider issue, switch failover)
- Document parsing failure rate > 10% (model regression)
- Quote send failures (email delivery issue)
- Database replication lag
- Cost burn rate per org > expected (runaway LLM usage)

### SLOs
- API availability: 99.9% (43m downtime/mjesec)
- Document processing latency: p95 < 60s (zavisi o velikosti)
- LLM call p95 < 10s
- Quote PDF generation p95 < 5s

### Backups
- Postgres: PITR, daily full + WAL streaming, retention 35 dana, monthly archive 1 godina
- Object storage: versioning enabled + cross-region replication za enterprise
- DR drill kvartalno

---

## 15. Cost Model — realistično

Ovo je dio koji se uvijek preskoči pa onda iznenadi. Računamo grubo per processed document.

**Po dokumentu (RFQ s ~50 stavki):**
- Storage: zanemarivo (< $0.001)
- OCR (Azure DI ili Textract): $0.01–0.05 za text PDF, $0.50–2.00 za skenirani višestrani dokument
- LLM extraction (Claude Sonnet ili GPT-4 class): ~5-15k input tokena + ~2-5k output tokena → $0.05–$0.30
- LLM matching (per item, batched): ~50 items × ~500 tokens = 25k tokena → $0.10–$0.20
- Embedding: zanemarivo
- Compute (worker time): ~30-90s CPU → $0.005

**Per quote total estimate: $0.20–$2.50** ovisno o tipu dokumenta.

**Mjesečno za ~1000 ponuda:** $200-$2500 samo LLM/OCR. Plus hosting (~$200-1000 za rani stage), Postgres ($50-500), email provider ($30-300), monitoring ($50-300).

**Bruto SaaS pricing target:** $200-1000 per user per month za enterprise pricing s ovim COGS-om — daje zdrav 80%+ gross margin.

Ovo treba pratiti per organization. Klijent koji bombardira sustav s 10.000 dokumenata mjesečno mora biti na pricing tieru koji to pokriva, ili imati per-document overage fee.

---

## 16. Internacionalizacija i lokalizacija

### Jezici koje sustav podržava
- UI: na razini frontenda preko `next-intl` ili `lingui`. Početno: en, hr, de, it, es, fr. Dodaj po potrebi.
- Document parsing: LLM podržava sve glavne jezike out of the box; OCR moraš provjeriti per service (Azure DI ima 100+ jezika, dobro pokriva)
- Output ponuda: template u jeziku klijenta (default jezik klijenta na client record)

### Format prikaza
- Brojevi: Intl.NumberFormat s locale klijenta
- Datumi: Intl.DateTimeFormat
- Valute: ISO 4217 code + simbol prema locale
- Adrese: structured (line1, line2, city, region, postal_code, country_code), prikaz formatiran prema country

### Jurisdikcijska pravila
- Tax engine pluggable per country (vidi sekciju 8.4)
- E-invoicing format pluggable per country (vidi sekciju 8.5)
- Payment methods pluggable per region (SEPA EU, ACH US, FPS UK, faster payments local)

### Globalno-prvo razmišljanje
Aplikacija je od početka multi-currency, multi-tax, multi-language. NEMA "hardcoded EUR" ili "VAT 25% always". Svaki monetarni iznos u bazi ima eksplicitnu valutu. Svaki tekst u UI ide kroz i18n.

---

## 17. Integracije (Faza 4+)

Ne gradimo sve odjednom. Po prioritetu:

**Email:**
- IMAP/Microsoft Graph za čitanje inboxa i auto-import RFQ-ova
- SMTP/SendGrid/Postmark za slanje ponuda

**Computing & files:**
- Google Drive, OneDrive za upload pipelinea
- Dropbox po potrebi

**Accounting & ERP:**
- QuickBooks Online, Xero, Sage (EN tržišta)
- DATEV (DE)
- Pantheon, Minimax, 4D Wand (HR/SLO)
- SAP Business One (mid-market)
- Odoo open-source

**CRM:**
- HubSpot, Salesforce, Pipedrive — sync clientsa i pipelinea

**Banking:**
- Open Banking APIs (PSD2 EU) za reconciliation
- Stripe za naplatu SaaS pretplate (ne za naplatu klijentovim klijentima)

**Logistika:**
- DHL, FedEx, UPS, GLS API za shipping quotes (input u landed cost calculation)

Sve integracije idu kroz webhook + queue pattern, retries, idempotency keys, sandbox testing.

---

## 18. Rizici i otvorena pitanja

Pošteno na stol.

**Rizik 1: Cold start podataka.** Sustav je vrijedan tek kad ima katalog i povijest. Onboarding novog klijenta podrazumijeva import njihovog postojećeg kataloga i barem neke povijesti ponuda. Ako klijent ne želi/ne može to dati, vrijednost u prvih X mjeseci je niska.

**Rizik 2: Točnost ekstrakcije iz "divljih" dokumenata.** Troškovnici koje šalju arhitekti su često PDF skenovi sa rukopisom, anotacijama, ispravljenim brojevima. Naša točnost na takvima neće biti 95% nikad. Trebamo to honest komunicirati i raditi review UI doista dobro.

**Rizik 3: LLM ovisnost.** Ako Claude/OpenAI značajno povise cijene ili promijene API, naš unit economics se mijenja. Mitigacija: provider apstrakcija + open-source fallback za nekritične zadatke.

**Rizik 4: Multi-jurisdikcijska kompleksnost.** Porez i e-invoicing variraju ozbiljno. Kupci očekuju lokalnu compliance. Ne možemo pokriti sve odmah. Strategija: kreni s 3-5 ključnih tržišta, ostalo "supported with manual configuration".

**Rizik 5: Data security incident.** Cijene dobavljača i klijenata su konkurentski osjetljive. Jedna povreda može uništiti reputaciju. Treba ozbiljan security program od dana 1, ne kasnije.

**Otvoreno pitanje 1:** Self-hosted opcija za enterprise klijente koji ne žele cloud SaaS? Veliki commitment, ali otključava enterprise dealove. Odluka u Fazi 4.

**Otvoreno pitanje 2:** White-label za partnere (distributere koji svojim klijentima nude alat)? Mijenja arhitekturu auth/branding sloja. Odluka kasnije.

**Otvoreno pitanje 3:** Marketplace dobavljača — agregirani katalog svih dobavljača svih organizacija (anonimizirano)? Ogromna vrijednost ali kompleksna privacy/data ownership pitanja. Vrlo kasno, ako uopće.

---

## 19. Sažetak — što sljedeće

Ako bih ovo gradio od nule, sljedeća 3 koraka bi bila:

1. **Diskovery week:** intervjui s 5-10 potencijalnih korisnika (sales/procurement people u rasvjeti i elektri), gledaj im preko ramena kako rade danas. Validiraj da Faza 1-3 zaista skraćuje njihovo vrijeme za ponudu.

2. **Tehnički prototip:** Faza 0 + Faza 1 (samo extraction). 6 tjedana solo dev ili 4 tjedna 2-člana tima. Cilj: stvarni operater može uploadati svoj dokument i vidjeti ekstrahirane stavke.

3. **Pilot s 1 prijateljskom firmom:** prije masovne gradnje, jedan klijent koristi prototip mjesec dana. Snimi sve frikcije. Tek tada nastavi gradnju.

Ovaj dokument je živi document. Verzioniraj ga u Gitu. Svaka faza zatvara se s retrospektivom koja ažurira ovaj spec.

---

*Konec.*
