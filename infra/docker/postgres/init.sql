-- =============================================================================
-- PostgreSQL extension setup — runs on first DB init via docker-entrypoint
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "vector";      -- pgvector for embeddings
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- fuzzy text matching
CREATE EXTENSION IF NOT EXISTS "citext";      -- case-insensitive text

-- Verify extensions loaded
DO $$
BEGIN
    RAISE NOTICE 'Extensions loaded: pgcrypto, vector, pg_trgm, citext';
END $$;
