-- 024: Goal scheduling — cron expressions, next run tracking, completion counting

ALTER TABLE goals ADD COLUMN IF NOT EXISTS schedule_cron TEXT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS schedule_next_at TIMESTAMPTZ;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS schedule_last_ran_at TIMESTAMPTZ;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS max_completions INTEGER;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS completion_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS created_via TEXT NOT NULL DEFAULT 'api';

-- Index for efficient schedule checking (Cortex PERCEIVE phase)
CREATE INDEX IF NOT EXISTS goals_schedule_due_idx
    ON goals (schedule_next_at)
    WHERE status = 'active'
      AND schedule_cron IS NOT NULL
      AND schedule_next_at IS NOT NULL;

COMMENT ON COLUMN goals.schedule_cron IS 'Cron expression (e.g. "0 8 * * 1-5") — NULL means no schedule';
COMMENT ON COLUMN goals.schedule_next_at IS 'Next scheduled execution time — advanced by Cortex after each run';
COMMENT ON COLUMN goals.max_completions IS 'NULL = unlimited recurring, 1 = one-shot reminder';
COMMENT ON COLUMN goals.created_via IS 'api | chat | cortex — how the goal was created';
