-- 065_quality_v2.sql
-- AI Quality v2: config snapshots + dimension_scores + status canonicalization

-- Snapshot table — hash-deduped, captures config at benchmark/loop boundaries
CREATE TABLE IF NOT EXISTS quality_config_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_hash TEXT UNIQUE NOT NULL,
    config JSONB NOT NULL,
    captured_at TIMESTAMPTZ DEFAULT NOW(),
    captured_by TEXT NOT NULL,
    tenant_id UUID
);

CREATE INDEX IF NOT EXISTS idx_quality_config_snapshots_hash
    ON quality_config_snapshots (config_hash);

-- Schema additions to existing benchmark runs table
ALTER TABLE quality_benchmark_runs
    ADD COLUMN IF NOT EXISTS config_snapshot_id UUID REFERENCES quality_config_snapshots(id),
    ADD COLUMN IF NOT EXISTS dimension_scores JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS vocabulary_version INT DEFAULT 2,
    ADD COLUMN IF NOT EXISTS error_summary TEXT;

-- Canonicalize status: 'complete' (legacy) -> 'completed'
UPDATE quality_benchmark_runs
SET status = 'completed'
WHERE status = 'complete';

-- Seed runtime-config defaults for retrieval tuning (Loop A)
-- These keys are read by memory-service; defaults are conservative
INSERT INTO platform_config (key, value, updated_at)
VALUES
    ('retrieval.top_k',          '5'::jsonb,   NOW()),
    ('retrieval.threshold',      '0.5'::jsonb, NOW()),
    ('retrieval.spread_weight',  '0.4'::jsonb, NOW()),
    ('quality.cortex_poll_interval_sec',         '1800'::jsonb, NOW()),
    ('quality.instruction_adherence_live',       'false'::jsonb, NOW()),
    ('quality.loops.retrieval_tuning.agency',    '"alert_only"'::jsonb, NOW())
ON CONFLICT (key) DO NOTHING;
