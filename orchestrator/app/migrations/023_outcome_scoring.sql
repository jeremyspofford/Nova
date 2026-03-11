-- 023: Outcome scoring infrastructure

-- Confidence column for weighted effectiveness matrix
ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS outcome_confidence REAL;

-- Conversation-level outcome tracking
CREATE TABLE IF NOT EXISTS conversation_outcomes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    session_id TEXT,
    session_score REAL NOT NULL,
    turn_count INTEGER NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_outcomes_conv
    ON conversation_outcomes (conversation_id);

-- Index for chat scorer: find usage events by session + time
CREATE INDEX IF NOT EXISTS idx_usage_events_session_created
    ON usage_events (session_id, created_at)
    WHERE session_id IS NOT NULL;
