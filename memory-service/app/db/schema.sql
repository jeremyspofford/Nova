-- Nova Memory Service — PostgreSQL 16 + pgvector schema
-- Run once during database initialization

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- trigram for fuzzy keyword search

-- ─────────────────────────────────────────────────────────────────────────────
-- Working memory: hot path, short-lived facts in active sessions.
-- Backed by Redis cache — this table is the durable fallback.
-- HNSW: m=16, ef=64 — fast rebuild, frequently purged.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS working_memories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   halfvec(768),           -- halfvec = 50% storage vs float4
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,
    tsv         TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

CREATE INDEX IF NOT EXISTS working_mem_agent_idx    ON working_memories (agent_id);
CREATE INDEX IF NOT EXISTS working_mem_expires_idx  ON working_memories (expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS working_mem_tsv_idx      ON working_memories USING GIN (tsv);
CREATE INDEX IF NOT EXISTS working_mem_hnsw_idx     ON working_memories
    USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64);

-- ─────────────────────────────────────────────────────────────────────────────
-- Episodic memory: conversation history, partitioned by month for lifecycle mgmt.
-- Partitioned table allows dropping old months without vacuuming.
-- HNSW: m=16, ef=64 (same as working, high-volume inserts).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS episodic_memories (
    id          UUID NOT NULL DEFAULT gen_random_uuid(),
    agent_id    TEXT NOT NULL,
    session_id  TEXT,
    content     TEXT NOT NULL,
    embedding   halfvec(768),
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    tsv         TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- Create partitions for current and next 3 months — extend via cron
CREATE TABLE IF NOT EXISTS episodic_memories_2026_01 PARTITION OF episodic_memories
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE IF NOT EXISTS episodic_memories_2026_02 PARTITION OF episodic_memories
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE IF NOT EXISTS episodic_memories_2026_03 PARTITION OF episodic_memories
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS episodic_memories_2026_04 PARTITION OF episodic_memories
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

CREATE INDEX IF NOT EXISTS episodic_mem_agent_idx ON episodic_memories (agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS episodic_mem_session_idx ON episodic_memories (session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS episodic_mem_tsv_idx ON episodic_memories USING GIN (tsv);

-- ─────────────────────────────────────────────────────────────────────────────
-- Semantic memory: extracted facts and entity relationships.
-- HNSW: m=24, ef=128 — higher recall, less frequent rebuilds.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS semantic_memories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   halfvec(768),
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INT NOT NULL DEFAULT 1,  -- optimistic concurrency for shared blocks
    tsv         TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

CREATE INDEX IF NOT EXISTS semantic_mem_agent_idx ON semantic_memories (agent_id);
CREATE INDEX IF NOT EXISTS semantic_mem_tsv_idx   ON semantic_memories USING GIN (tsv);
CREATE INDEX IF NOT EXISTS semantic_mem_meta_idx  ON semantic_memories USING GIN (metadata);
CREATE INDEX IF NOT EXISTS semantic_mem_hnsw_idx  ON semantic_memories
    USING hnsw (embedding halfvec_cosine_ops) WITH (m = 24, ef_construction = 128);

-- ─────────────────────────────────────────────────────────────────────────────
-- Procedural memory: task patterns and how-to knowledge.
-- Low volume, high-value. HNSW same as semantic.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS procedural_memories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   halfvec(768),
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    tsv         TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

CREATE INDEX IF NOT EXISTS procedural_mem_agent_idx ON procedural_memories (agent_id);
CREATE INDEX IF NOT EXISTS procedural_mem_tsv_idx   ON procedural_memories USING GIN (tsv);
CREATE INDEX IF NOT EXISTS procedural_mem_hnsw_idx  ON procedural_memories
    USING hnsw (embedding halfvec_cosine_ops) WITH (m = 24, ef_construction = 128);

-- ─────────────────────────────────────────────────────────────────────────────
-- Embedding cache: avoids re-embedding identical text (24h TTL enforced in app)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS embedding_cache (
    content_hash TEXT PRIMARY KEY,
    embedding    halfvec(768) NOT NULL,
    model        TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
