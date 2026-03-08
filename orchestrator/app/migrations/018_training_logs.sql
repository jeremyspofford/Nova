-- 018: Pipeline training data logs
-- Captures full prompt/response pairs per pipeline stage for future SLM fine-tuning.
-- Feature-gated by pipeline.training_log_enabled in platform_config.

CREATE TABLE IF NOT EXISTS pipeline_training_logs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id          UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_session_id UUID REFERENCES agent_sessions(id) ON DELETE SET NULL,
    role             TEXT NOT NULL,
    prompt           JSONB NOT NULL,
    response         TEXT NOT NULL,
    model            TEXT NOT NULL,
    input_tokens     INTEGER DEFAULT 0,
    output_tokens    INTEGER DEFAULT 0,
    cost_usd         NUMERIC(12, 8),
    complexity       TEXT,
    pipeline_success BOOLEAN,
    stage_verdict    TEXT,
    was_fallback     BOOLEAN DEFAULT false,
    temperature      FLOAT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ptl_role_idx ON pipeline_training_logs(role);
CREATE INDEX IF NOT EXISTS ptl_created_idx ON pipeline_training_logs(created_at DESC);

INSERT INTO platform_config (key, value) VALUES
    ('pipeline.training_log_enabled', '"false"'::jsonb)
ON CONFLICT (key) DO NOTHING;
