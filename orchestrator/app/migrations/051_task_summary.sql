-- 051_task_summary.sql
-- Add structured summary JSONB to tasks (populated at completion, no LLM call)
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS summary JSONB;

COMMENT ON COLUMN tasks.summary IS 'Structured summary: headline, files_created, files_modified, findings_count, review_verdict, cost_usd, duration_s';
