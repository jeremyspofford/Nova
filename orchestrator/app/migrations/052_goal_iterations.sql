-- 052_goal_iterations.sql
-- Track every goal attempt (success or failure) for timeline display
CREATE TABLE IF NOT EXISTS goal_iterations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id         UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    attempt         INTEGER NOT NULL,
    cycle_number    INTEGER NOT NULL,
    plan_text       TEXT,
    task_id         UUID REFERENCES tasks(id) ON DELETE SET NULL,
    task_status     TEXT,
    task_summary    TEXT,
    cost_usd        NUMERIC(10, 6) DEFAULT 0,
    files_touched   JSONB DEFAULT '[]',
    plan_adjustment TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(goal_id, attempt)
);

CREATE INDEX IF NOT EXISTS idx_goal_iterations_goal ON goal_iterations(goal_id);

-- Update DocumentationAgent to produce task_summary artifacts
UPDATE pod_agents SET artifact_type = 'task_summary' WHERE role = 'documentation';
