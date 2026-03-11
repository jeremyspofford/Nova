-- 022: Add adaptive routing columns to usage_events
-- metadata: stores task_type, caller identity, pipeline stage context
-- outcome_score: 0.0-1.0 quality score for model effectiveness tracking

ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS outcome_score REAL;

-- Index for effectiveness matrix aggregation query
CREATE INDEX IF NOT EXISTS idx_usage_events_outcome
    ON usage_events (model, outcome_score)
    WHERE outcome_score IS NOT NULL;
