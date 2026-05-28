-- =============================================================================
-- AI Quote & Procurement Platform — Database Schema
-- PostgreSQL 16+ with pgvector, pg_trgm, citext extensions
-- =============================================================================

-- Extensions assumed loaded via infra/docker/postgres/init.sql

-- -----------------------------------------------------------------------------
-- ORGANIZATIONS (multi-tenant root)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    slug            TEXT UNIQUE NOT NULL,
    country_code    CHAR(2) NOT NULL,            -- ISO 3166-1 alpha-2
    base_currency   CHAR(3) NOT NULL,            -- ISO 4217
    locale          TEXT NOT NULL DEFAULT 'en',  -- BCP 47
    timezone        TEXT NOT NULL DEFAULT 'UTC', -- IANA tz
    settings        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- USERS & MEMBERSHIPS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email                           CITEXT UNIQUE NOT NULL,
    full_name                       TEXT NOT NULL,
    auth_provider                   TEXT,
    auth_subject                    TEXT,
    hashed_password                 TEXT,
    locale                          TEXT,
    is_active                       BOOLEAN NOT NULL DEFAULT TRUE,
    is_verified                     BOOLEAN NOT NULL DEFAULT FALSE,
    verification_token              VARCHAR(128),
    verification_token_expires_at   TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_users_verification_token ON users(verification_token);

CREATE TABLE IF NOT EXISTS memberships (
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('owner','admin','sales','procurement','viewer','approver')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);

-- -----------------------------------------------------------------------------
-- CLIENTS & CONTACTS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clients (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    legal_name          TEXT,
    tax_id              TEXT,
    country_code        CHAR(2) NOT NULL,
    industry            TEXT,
    segment             TEXT,
    payment_terms_days  INT NOT NULL DEFAULT 30,
    credit_limit        NUMERIC(14,2),
    risk_score          NUMERIC(3,2),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, tax_id)
);
CREATE INDEX IF NOT EXISTS idx_clients_org ON clients(org_id);

CREATE TABLE IF NOT EXISTS contacts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id   UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    full_name   TEXT NOT NULL,
    email       CITEXT,
    phone       TEXT,
    role        TEXT,
    is_primary  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- SUPPLIERS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS suppliers (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    country_code        CHAR(2) NOT NULL,
    currency            CHAR(3) NOT NULL,
    incoterms_default   TEXT,
    lead_time_days_avg  INT,
    rating              NUMERIC(3,2),
    on_time_rate        NUMERIC(3,2),
    quality_score       NUMERIC(3,2),
    email               CITEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_suppliers_org ON suppliers(org_id);

-- -----------------------------------------------------------------------------
-- PRODUCTS (canonical catalog)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    sku             TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    category        TEXT,
    brand           TEXT,
    specs           JSONB,
    unit            TEXT NOT NULL DEFAULT 'pcs',
    embedding       vector(1536),
    search_text     tsvector,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, sku)
);
CREATE INDEX IF NOT EXISTS idx_products_org ON products(org_id);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_search ON products USING gin (search_text);
CREATE INDEX IF NOT EXISTS idx_products_name_trgm ON products USING gin (name gin_trgm_ops);
-- pgvector index — create after data exists (ivfflat needs sample data)
-- CREATE INDEX idx_products_embedding ON products USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- -----------------------------------------------------------------------------
-- WAREHOUSE / STOCK
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_locations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    address     TEXT,
    country_code CHAR(2),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock_items (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    product_id              UUID REFERENCES products(id) ON DELETE SET NULL,
    location_id             UUID REFERENCES stock_locations(id),
    sku                     TEXT NOT NULL,
    name                    TEXT NOT NULL,
    category                TEXT,
    unit                    TEXT NOT NULL DEFAULT 'pcs',
    quantity_on_hand        NUMERIC(14,4) NOT NULL DEFAULT 0,
    quantity_reserved       NUMERIC(14,4) NOT NULL DEFAULT 0,
    min_stock_level         NUMERIC(14,4) NOT NULL DEFAULT 0,
    unit_cost               NUMERIC(14,4),
    currency                CHAR(3) NOT NULL DEFAULT 'EUR',
    last_received_at        TIMESTAMPTZ,
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, sku, location_id)
);
CREATE INDEX IF NOT EXISTS idx_stock_org ON stock_items(org_id);
CREATE INDEX IF NOT EXISTS idx_stock_product ON stock_items(product_id);
CREATE INDEX IF NOT EXISTS idx_stock_low ON stock_items(org_id) WHERE quantity_on_hand < min_stock_level;

-- Stock movements (audit trail of every quantity change)
CREATE TABLE IF NOT EXISTS stock_movements (
    id              BIGSERIAL PRIMARY KEY,
    stock_item_id   UUID NOT NULL REFERENCES stock_items(id) ON DELETE CASCADE,
    movement_type   TEXT NOT NULL CHECK (movement_type IN ('receipt','issue','adjustment','reserve','release','transfer')),
    quantity_delta  NUMERIC(14,4) NOT NULL,  -- positive or negative
    reference_type  TEXT,                    -- 'quote','manual','import',...
    reference_id    UUID,
    reason          TEXT,
    user_id         UUID REFERENCES users(id),
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_stock_movements_item ON stock_movements(stock_item_id, occurred_at DESC);

-- -----------------------------------------------------------------------------
-- SUPPLIER PRODUCTS (one product → N suppliers with different prices)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS supplier_products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    supplier_id     UUID NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    supplier_sku    TEXT,
    supplier_name   TEXT,
    moq             INT NOT NULL DEFAULT 1,
    pack_size       INT NOT NULL DEFAULT 1,
    lead_time_days  INT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id, supplier_id)
);
CREATE INDEX IF NOT EXISTS idx_supplier_products_product ON supplier_products(product_id);
CREATE INDEX IF NOT EXISTS idx_supplier_products_supplier ON supplier_products(supplier_id);

CREATE TABLE IF NOT EXISTS supplier_price_history (
    id                  BIGSERIAL PRIMARY KEY,
    supplier_product_id UUID NOT NULL REFERENCES supplier_products(id) ON DELETE CASCADE,
    unit_price          NUMERIC(14,4) NOT NULL,
    currency            CHAR(3) NOT NULL,
    valid_from          TIMESTAMPTZ NOT NULL,
    valid_to            TIMESTAMPTZ,
    source              TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_price_hist_sp ON supplier_price_history(supplier_product_id, valid_from DESC);

-- -----------------------------------------------------------------------------
-- FX RATES (snapshot, append-only)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fx_rates (
    base_ccy        CHAR(3) NOT NULL,
    quote_ccy       CHAR(3) NOT NULL,
    rate            NUMERIC(18,8) NOT NULL,
    source          TEXT NOT NULL,
    as_of           TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (base_ccy, quote_ccy, as_of)
);

-- -----------------------------------------------------------------------------
-- TAX RULES (pluggable per jurisdiction)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tax_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID REFERENCES organizations(id) ON DELETE CASCADE,
    country_code    CHAR(2) NOT NULL,
    region          TEXT,
    rule_type       TEXT NOT NULL,
    rate            NUMERIC(5,4),
    applies_when    JSONB,
    valid_from      DATE NOT NULL,
    valid_to        DATE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tax_country ON tax_rules(country_code);

-- -----------------------------------------------------------------------------
-- PROJECTS (umbrella for one RFQ/deal)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    client_id           UUID REFERENCES clients(id),
    name                TEXT NOT NULL,
    project_type        TEXT,
    status              TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','quoting','submitted','won','lost','withdrawn','on_hold')),
    estimated_value     NUMERIC(14,2),
    estimated_value_ccy CHAR(3),
    deadline_at         TIMESTAMPTZ,
    site_country        CHAR(2),
    site_region         TEXT,
    urgency             TEXT,
    assigned_to         UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_projects_org_status ON projects(org_id, status);

-- -----------------------------------------------------------------------------
-- DOCUMENTS & EXTRACTIONS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id      UUID REFERENCES projects(id) ON DELETE SET NULL,
    uploaded_by     UUID REFERENCES users(id),
    storage_key     TEXT NOT NULL,
    filename        TEXT NOT NULL,
    mime_type       TEXT,
    size_bytes      BIGINT,
    checksum        TEXT,
    source          TEXT,
    detected_lang   TEXT,
    status          TEXT NOT NULL DEFAULT 'received'
        CHECK (status IN ('received','parsing','parsed','failed','reviewed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_documents_org ON documents(org_id);

CREATE TABLE IF NOT EXISTS document_extractions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id         UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    raw_text            TEXT,
    structured_data     JSONB,
    extraction_method   TEXT,
    confidence          NUMERIC(3,2),
    needs_review        BOOLEAN NOT NULL DEFAULT TRUE,
    reviewed_by         UUID REFERENCES users(id),
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- QUOTES
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quotes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version         INT NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','review','approved','sent','accepted','rejected','expired')),
    currency        CHAR(3) NOT NULL,
    fx_snapshot     JSONB,
    fx_locked_at    TIMESTAMPTZ,
    fx_locked_by    UUID REFERENCES users(id),
    subtotal        NUMERIC(14,2),
    discount_total  NUMERIC(14,2) NOT NULL DEFAULT 0,
    tax_total       NUMERIC(14,2),
    total           NUMERIC(14,2),
    cost_total      NUMERIC(14,2),
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
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, version)
);
CREATE INDEX IF NOT EXISTS idx_quotes_org_status ON quotes(org_id, status);

CREATE TABLE IF NOT EXISTS quote_line_items (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quote_id                UUID NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    position                INT NOT NULL,
    product_id              UUID REFERENCES products(id),
    supplier_product_id     UUID REFERENCES supplier_products(id),
    stock_item_id           UUID REFERENCES stock_items(id),
    description             TEXT NOT NULL,
    quantity                NUMERIC(14,4) NOT NULL,
    unit                    TEXT NOT NULL,
    unit_cost               NUMERIC(14,4),
    unit_price              NUMERIC(14,4) NOT NULL,
    discount_pct            NUMERIC(5,4) NOT NULL DEFAULT 0,
    tax_rate                NUMERIC(5,4),
    line_total              NUMERIC(14,2),
    margin_pct              NUMERIC(5,4),
    notes                   TEXT
);
CREATE INDEX IF NOT EXISTS idx_quote_lines_quote ON quote_line_items(quote_id);

CREATE TABLE IF NOT EXISTS quote_outcomes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quote_id        UUID NOT NULL UNIQUE REFERENCES quotes(id) ON DELETE CASCADE,
    outcome         TEXT NOT NULL CHECK (outcome IN ('won','lost','withdrawn','expired','no_response')),
    reason          TEXT,
    competitor_name TEXT,
    competitor_price NUMERIC(14,2),
    lessons         TEXT,
    recorded_by     UUID REFERENCES users(id),
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- AUDIT LOG (append-only)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    org_id          UUID NOT NULL,
    user_id         UUID,
    action          TEXT NOT NULL,
    entity_type     TEXT,
    entity_id       UUID,
    before_state    JSONB,
    after_state     JSONB,
    ip_address      INET,
    user_agent      TEXT,
    at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_org_at ON audit_log(org_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action, at DESC);

-- -----------------------------------------------------------------------------
-- VIEWS for common queries
-- -----------------------------------------------------------------------------

-- Low stock alert view
CREATE OR REPLACE VIEW v_low_stock AS
SELECT
    si.org_id,
    si.id,
    si.sku,
    si.name,
    si.quantity_on_hand,
    si.min_stock_level,
    (si.min_stock_level - si.quantity_on_hand) AS shortage,
    sl.name AS location_name,
    si.unit
FROM stock_items si
LEFT JOIN stock_locations sl ON si.location_id = sl.id
WHERE si.quantity_on_hand < si.min_stock_level;

-- Win rate per client (last 12 months)
CREATE OR REPLACE VIEW v_client_win_rate AS
SELECT
    c.id AS client_id,
    c.name AS client_name,
    c.org_id,
    COUNT(qo.id) AS total_outcomes,
    COUNT(qo.id) FILTER (WHERE qo.outcome = 'won') AS won_count,
    ROUND(
        COUNT(qo.id) FILTER (WHERE qo.outcome = 'won')::NUMERIC
        / NULLIF(COUNT(qo.id), 0) * 100,
        1
    ) AS win_rate_pct,
    SUM(q.total) FILTER (WHERE qo.outcome = 'won') AS won_value
FROM clients c
LEFT JOIN projects p ON p.client_id = c.id
LEFT JOIN quotes q ON q.project_id = p.id
LEFT JOIN quote_outcomes qo ON qo.quote_id = q.id
WHERE qo.recorded_at > now() - interval '12 months'
GROUP BY c.id, c.name, c.org_id;
