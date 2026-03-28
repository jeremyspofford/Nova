-- 046: Add missing composite indexes for frequently queried patterns.
--
-- tasks(status, last_heartbeat_at) — used by stale task reaper every 30s,
--   previously fell back to single-column status_idx + seq scan on heartbeat.
--
-- tasks(status, queued_at DESC) — used by the filtered task list endpoint
--   which ORDER BY queued_at DESC with optional status filter.
--
-- guardrail_findings(task_id) — used by single-task detail endpoint for
--   COUNT(*) subqueries. Currently unindexed FK.
--
-- code_reviews(task_id) — same as above.
--
-- artifacts(task_id) — same as above.

CREATE INDEX IF NOT EXISTS idx_tasks_status_heartbeat
    ON tasks (status, last_heartbeat_at DESC);

CREATE INDEX IF NOT EXISTS idx_tasks_status_queued
    ON tasks (status, queued_at DESC);

CREATE INDEX IF NOT EXISTS idx_guardrail_findings_task
    ON guardrail_findings (task_id);

CREATE INDEX IF NOT EXISTS idx_code_reviews_task
    ON code_reviews (task_id);

CREATE INDEX IF NOT EXISTS idx_artifacts_task
    ON artifacts (task_id);
