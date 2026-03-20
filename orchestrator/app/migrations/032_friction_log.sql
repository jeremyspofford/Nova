-- Friction log: lightweight issue tracker for dogfooding.
-- Entries track things that broke or felt wrong during usage.
-- "Fix This" creates a pipeline task from an entry.

CREATE TABLE IF NOT EXISTS friction_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    description     TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'annoyance'
                    CHECK (severity IN ('blocker', 'annoyance', 'idea')),
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'in_progress', 'fixed')),
    task_id         UUID REFERENCES tasks(id) ON DELETE SET NULL,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    screenshot_path TEXT,
    screenshot_thumb_path TEXT,
    source          TEXT NOT NULL DEFAULT 'manual'
                    CHECK (source IN ('manual', 'auto')),
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_friction_log_status ON friction_log(status);
CREATE INDEX IF NOT EXISTS idx_friction_log_severity ON friction_log(severity);
CREATE INDEX IF NOT EXISTS idx_friction_log_created_at ON friction_log(created_at DESC);

-- Pipeline stats optimization (from eng review):
-- Composite index for the pipeline_stats() query which uses FILTER on status + completed_at.
CREATE INDEX IF NOT EXISTS idx_tasks_status_completed
    ON tasks (status, completed_at DESC);
