-- Nova Memory Service — PostgreSQL 16 + pgvector schema
-- Run once during database initialization

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- trigram for fuzzy keyword search

-- ─────────────────────────────────────────────────────────────────────────────
-- Drop old 4-tier memory tables (replaced by engram network)
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS working_memories CASCADE;
DROP TABLE IF EXISTS episodic_memories CASCADE;
DROP TABLE IF EXISTS semantic_memories CASCADE;
DROP TABLE IF EXISTS procedural_memories CASCADE;

-- ─────────────────────────────────────────────────────────────────────────────
-- Embedding cache: avoids re-embedding identical text (24h TTL enforced in app)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS embedding_cache (
    content_hash TEXT PRIMARY KEY,
    embedding    halfvec(768) NOT NULL,
    model        TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Engram Network: graph-based cognitive memory
-- Engrams are atomic memory nodes; engram_edges are weighted typed associations.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS engrams (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type            TEXT NOT NULL,
        -- fact, episode, entity, preference, procedure, schema, goal, self_model
    content         TEXT NOT NULL,
    fragments       JSONB,              -- decomposed components (entities, actions, outcomes)
    embedding       halfvec(768),       -- for seed activation (matches existing embedding model)

    -- Temporal
    occurred_at     TIMESTAMPTZ,        -- when the memory was formed
    temporal_refs   JSONB,              -- {before: [uuid], after: [uuid], during: [uuid]}

    -- Valence & Activation
    importance      REAL NOT NULL DEFAULT 0.5,   -- 0.0-1.0, emotional/practical significance
    activation      REAL NOT NULL DEFAULT 1.0,   -- 0.0-1.0, readiness to be recalled (decays)
    access_count    INTEGER NOT NULL DEFAULT 0,
    last_accessed   TIMESTAMPTZ,

    -- Provenance
    source_type     TEXT NOT NULL DEFAULT 'chat',
        -- chat, pipeline, tool, consolidation, cortex, journal, external, self_reflection
    source_id       UUID,               -- conversation_id, task_id, goal_id, etc.
    confidence      REAL NOT NULL DEFAULT 0.8,   -- 0.0-1.0
    superseded      BOOLEAN NOT NULL DEFAULT FALSE,

    -- Multi-tenancy
    tenant_id       UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',

    -- Embedding model tracking
    embedding_model TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_engrams_type ON engrams(type);
CREATE INDEX IF NOT EXISTS idx_engrams_activation ON engrams(activation) WHERE NOT superseded;
CREATE INDEX IF NOT EXISTS idx_engrams_tenant ON engrams(tenant_id);
CREATE INDEX IF NOT EXISTS idx_engrams_source ON engrams(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_engrams_occurred ON engrams(occurred_at);
CREATE INDEX IF NOT EXISTS idx_engrams_content_tsv ON engrams USING GIN (to_tsvector('english', content));
CREATE INDEX IF NOT EXISTS idx_engrams_hnsw ON engrams
    USING hnsw (embedding halfvec_cosine_ops) WITH (m = 24, ef_construction = 128);

-- Engram edges: typed, weighted associations between engrams
CREATE TABLE IF NOT EXISTS engram_edges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
    target_id       UUID NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
    relation        TEXT NOT NULL,
        -- caused_by, related_to, contradicts, preceded, enables,
        -- part_of, instance_of, analogous_to
    weight          REAL NOT NULL DEFAULT 0.5,   -- 0.0-1.0, association strength
    co_activations  INTEGER NOT NULL DEFAULT 1,  -- Hebbian counter
    last_co_activated TIMESTAMPTZ DEFAULT NOW(),

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(source_id, target_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON engram_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON engram_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON engram_edges(relation);
CREATE INDEX IF NOT EXISTS idx_edges_weight ON engram_edges(weight);

-- Composite indexes for consolidation queries
CREATE INDEX IF NOT EXISTS idx_engrams_active_created
    ON engrams(created_at) WHERE NOT superseded;
CREATE INDEX IF NOT EXISTS idx_engrams_prune_candidates
    ON engrams(activation, access_count) WHERE NOT superseded;
CREATE INDEX IF NOT EXISTS idx_edges_decay_candidates
    ON engram_edges(created_at) WHERE co_activations <= 1;

-- Cold storage for superseded and pruned engrams (same schema, excluded from activation)
CREATE TABLE IF NOT EXISTS engram_archive (
    id              UUID PRIMARY KEY,
    type            TEXT NOT NULL,
    content         TEXT NOT NULL,
    fragments       JSONB,
    embedding       halfvec(768),
    occurred_at     TIMESTAMPTZ,
    temporal_refs   JSONB,
    importance      REAL NOT NULL DEFAULT 0.5,
    activation      REAL NOT NULL DEFAULT 0.0,
    access_count    INTEGER NOT NULL DEFAULT 0,
    last_accessed   TIMESTAMPTZ,
    source_type     TEXT NOT NULL DEFAULT 'chat',
    source_id       UUID,
    confidence      REAL NOT NULL DEFAULT 0.8,
    superseded      BOOLEAN NOT NULL DEFAULT TRUE,
    tenant_id       UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    embedding_model TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archive_reason  TEXT
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Consolidation log + Retrieval log (Neural Router)
-- ─────────────────────────────────────────────────────────────────────────────

-- Consolidation audit trail
CREATE TABLE IF NOT EXISTS consolidation_log (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_type            TEXT NOT NULL,   -- idle, scheduled, threshold, manual
    engrams_reviewed        INTEGER NOT NULL DEFAULT 0,
    schemas_created         INTEGER NOT NULL DEFAULT 0,
    edges_strengthened      INTEGER NOT NULL DEFAULT 0,
    edges_pruned            INTEGER NOT NULL DEFAULT 0,
    engrams_pruned          INTEGER NOT NULL DEFAULT 0,
    engrams_merged          INTEGER NOT NULL DEFAULT 0,
    contradictions_resolved INTEGER NOT NULL DEFAULT 0,
    self_model_updates      JSONB,
    model_used              TEXT,
    tokens_used             INTEGER,
    duration_ms             INTEGER,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Neural Router training data: what was retrieved vs. what was useful
CREATE TABLE IF NOT EXISTS retrieval_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_embedding     halfvec(768),
    query_text          TEXT,
    context_summary     TEXT,
    temporal_context    JSONB,         -- {time_of_day, day_of_week, active_goal}
    engrams_surfaced    UUID[],        -- engrams returned by activation
    engrams_used        UUID[],        -- engrams the LLM actually referenced (filled later)
    session_id          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_retrieval_log_created ON retrieval_log(created_at);

-- Working memory session state (tracks what's on the "desk" per session)
CREATE TABLE IF NOT EXISTS working_memory_slots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      TEXT NOT NULL,
    slot_type       TEXT NOT NULL,       -- pinned, sticky, refreshed, sliding, expiring
    engram_id       UUID REFERENCES engrams(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,        -- rendered content for this slot
    relevance_score REAL NOT NULL DEFAULT 1.0,
    token_count     INTEGER NOT NULL DEFAULT 0,
    turn_added      INTEGER NOT NULL DEFAULT 0,
    turn_last_relevant INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wm_slots_session ON working_memory_slots(session_id);
CREATE INDEX IF NOT EXISTS idx_wm_slots_type ON working_memory_slots(slot_type);

-- Outcome scoring feedback columns
ALTER TABLE engrams ADD COLUMN IF NOT EXISTS outcome_avg REAL DEFAULT NULL;
ALTER TABLE engrams ADD COLUMN IF NOT EXISTS outcome_count INTEGER DEFAULT 0;
ALTER TABLE engrams ADD COLUMN IF NOT EXISTS last_recalibrated_at TIMESTAMPTZ DEFAULT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- Neural Router: learned re-ranker model storage (Phase 5)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS neural_router_models (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                 UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    architecture              TEXT NOT NULL,
    weights                   BYTEA NOT NULL,
    observation_count         INTEGER NOT NULL,
    validation_precision_at_k REAL,
    is_active                 BOOLEAN NOT NULL DEFAULT FALSE,
    trained_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nrm_tenant_active
    ON neural_router_models(tenant_id) WHERE is_active;

-- Neural Router: add tenant_id to retrieval_log for per-tenant observation counts
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS tenant_id UUID
    NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001';
CREATE INDEX IF NOT EXISTS idx_retrieval_log_tenant ON retrieval_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_log_used ON retrieval_log(tenant_id)
    WHERE engrams_used IS NOT NULL;
