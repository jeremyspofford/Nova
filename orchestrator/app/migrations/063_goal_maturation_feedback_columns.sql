-- Migration 063: Goal maturation — rejection feedback + manual implementation note
-- The `spec` column already exists from migration 039.
-- Completes the schema for the goal maturation pipeline (executor logic in cortex).

ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec_rejection_feedback TEXT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS manual_implementation_note TEXT;
