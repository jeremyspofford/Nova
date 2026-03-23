-- Migration 036: Add success_criteria to goals
-- Idempotent: ADD COLUMN IF NOT EXISTS.

ALTER TABLE goals ADD COLUMN IF NOT EXISTS success_criteria TEXT;

COMMENT ON COLUMN goals.success_criteria IS
    'Measurable conditions that define when this goal is progressing or achieved. '
    'Goals describe conditions to maintain, not tasks to complete.';
