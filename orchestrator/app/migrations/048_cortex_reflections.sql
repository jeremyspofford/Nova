-- 048_cortex_reflections.sql
-- Structured experience log for Cortex goal learning.
-- Records what was tried, what happened, and lessons learned per goal cycle.

CREATE TABLE IF NOT EXISTS cortex_reflections (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id           UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    cycle_number      INTEGER NOT NULL,
    drive             TEXT NOT NULL DEFAULT 'serve',
    maturation_phase  TEXT,
    task_id           UUID,

    -- What was tried
    approach          TEXT NOT NULL,
    approach_hash     TEXT NOT NULL,

    -- What happened
    outcome           TEXT NOT NULL CHECK (outcome IN (
                          'success', 'partial', 'failure', 'timeout', 'cancelled', 'escalated'
                      )),
    outcome_score     REAL NOT NULL,
    lesson            TEXT,
    failure_mode      TEXT,

    -- Conditions at time of reflection
    context_snapshot  JSONB DEFAULT '{}',

    created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Primary query: recent reflections for a goal
CREATE INDEX IF NOT EXISTS cortex_reflections_goal_created_idx
    ON cortex_reflections (goal_id, created_at DESC);

-- Filter by outcome for stuck detection
CREATE INDEX IF NOT EXISTS cortex_reflections_goal_outcome_idx
    ON cortex_reflections (goal_id, outcome);

-- Approach dedup lookup
CREATE INDEX IF NOT EXISTS cortex_reflections_goal_hash_idx
    ON cortex_reflections (goal_id, approach_hash);
