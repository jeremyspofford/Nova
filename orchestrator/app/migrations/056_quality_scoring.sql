-- 056_quality_scoring.sql
-- AI Quality Measurement: scoring table + benchmark runs table

CREATE TABLE IF NOT EXISTS quality_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,  -- nullable for pipeline task scores
    message_id UUID,
    task_id UUID,
    dimension TEXT NOT NULL,
    score REAL NOT NULL,
    confidence REAL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_scores_dimension_time
    ON quality_scores (dimension, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_scores_conversation
    ON quality_scores (conversation_id, created_at DESC);

CREATE TABLE IF NOT EXISTS quality_benchmark_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status TEXT DEFAULT 'running',
    composite_score NUMERIC(5,2),
    category_scores JSONB DEFAULT '{}',
    case_results JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}'
);

-- Seed backend pause feature flags (default: enabled)
INSERT INTO platform_config (key, value, updated_at)
VALUES
    ('features.cortex_loop', 'true'::jsonb, NOW()),
    ('features.intel_polling', 'true'::jsonb, NOW()),
    ('features.knowledge_crawling', 'true'::jsonb, NOW())
ON CONFLICT (key) DO NOTHING;
