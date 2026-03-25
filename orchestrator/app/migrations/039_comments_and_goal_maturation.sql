-- Migration 039: Unified comments table and goal maturation columns

CREATE TABLE IF NOT EXISTS comments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('recommendation', 'goal')),
    entity_id   UUID NOT NULL,
    author_type TEXT NOT NULL CHECK (author_type IN ('human', 'nova')),
    author_name TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_comments_entity ON comments(entity_type, entity_id);

-- Goal maturation extensions
ALTER TABLE goals ADD COLUMN IF NOT EXISTS maturation_status TEXT
    CHECK (maturation_status IN ('triaging', 'scoping', 'speccing', 'review', 'building', 'verifying'));
ALTER TABLE goals ADD COLUMN IF NOT EXISTS complexity TEXT
    CHECK (complexity IN ('simple', 'complex'));
ALTER TABLE goals ADD COLUMN IF NOT EXISTS scope_analysis JSONB;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec TEXT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec_approved_at TIMESTAMPTZ;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec_approved_by TEXT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS source_recommendation_id UUID REFERENCES intel_recommendations(id);

-- Update created_via comment to include 'system'
COMMENT ON COLUMN goals.created_via IS 'How the goal was created: api | chat | cortex | system';
