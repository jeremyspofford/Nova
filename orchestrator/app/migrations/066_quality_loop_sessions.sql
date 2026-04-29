-- 066_quality_loop_sessions.sql
-- One row per QualityLoop iteration. Records baseline, proposal,
-- application, verification, and decision.

CREATE TABLE IF NOT EXISTS quality_loop_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loop_name TEXT NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    baseline_snapshot_id UUID REFERENCES quality_config_snapshots(id),
    baseline_run_id UUID REFERENCES quality_benchmark_runs(id),
    proposed_changes JSONB NOT NULL,
    applied BOOLEAN DEFAULT FALSE,
    verification_run_id UUID REFERENCES quality_benchmark_runs(id),
    outcome TEXT,
    decision TEXT,
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    notes JSONB DEFAULT '{}'::jsonb,
    tenant_id UUID
);

CREATE INDEX IF NOT EXISTS idx_quality_loop_sessions_loop_started
    ON quality_loop_sessions (loop_name, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_quality_loop_sessions_pending
    ON quality_loop_sessions (decision)
    WHERE decision = 'pending_approval';
