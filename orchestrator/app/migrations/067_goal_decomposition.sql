-- Migration 067: goal decomposition + maturation executor
-- Builds on the latest sequential baseline (063 goal_maturation_feedback_columns,
-- 064 brain_default_off, 065 quality_v2, 066 quality_loop_sessions).
-- All ADDs are idempotent.

-- ── Structured artifacts produced by speccing ────────────────────────────────
ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec_children JSONB;
COMMENT ON COLUMN goals.spec_children IS
    'Immediate children planned by speccing. JSON array of '
    '{title, description, hint, depends_on:[indices], estimated_cost_usd, estimated_complexity}.';

ALTER TABLE goals ADD COLUMN IF NOT EXISTS verification_commands JSONB;
COMMENT ON COLUMN goals.verification_commands IS
    'Shell commands the verifier runs to prove this goal completed. '
    'JSON array of {cmd, cwd, timeout_s}.';

ALTER TABLE goals ADD COLUMN IF NOT EXISTS success_criteria_structured JSONB;
COMMENT ON COLUMN goals.success_criteria_structured IS
    'Machine-evaluable criteria. Array of {statement, check, check_arg} where '
    'check ∈ (''command'', ''engram_query'', ''llm_judge''). '
    'Legacy success_criteria TEXT remains; verifier reads structured first, falls back to TEXT.';

-- ── Review + retry policy ────────────────────────────────────────────────────
ALTER TABLE goals ADD COLUMN IF NOT EXISTS review_policy TEXT NOT NULL DEFAULT 'cost-above-2'
    CHECK (review_policy IN ('top-only', 'all', 'cost-above-2', 'cost-above-5', 'scopes-sensitive'));
ALTER TABLE goals ADD COLUMN IF NOT EXISTS max_depth INTEGER NOT NULL DEFAULT 5;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS depth INTEGER NOT NULL DEFAULT 0;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 2;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;

-- ── Maturation phase: add 'waiting' (parent blocked on children) ─────────────
ALTER TABLE goals DROP CONSTRAINT IF EXISTS goals_maturation_status_check;
ALTER TABLE goals ADD CONSTRAINT goals_maturation_status_check
    CHECK (maturation_status IS NULL OR maturation_status IN
        ('triaging', 'scoping', 'speccing', 'review', 'building', 'waiting', 'verifying'));

-- ── Per-attempt verification record ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS goal_verifications (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id        UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    attempt        INTEGER NOT NULL,
    cmd_results    JSONB,
    quartet_review JSONB,
    criteria_eval  JSONB,
    aggregate      TEXT NOT NULL CHECK (aggregate IN ('pass', 'fail', 'human-review')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS goal_verifications_goal_idx ON goal_verifications(goal_id);

-- ── Index for cycle's "find parent ready to verify" query ───────────────────
CREATE INDEX IF NOT EXISTS goals_parent_status_idx
    ON goals(parent_goal_id, status) WHERE parent_goal_id IS NOT NULL;

-- ── max_cost_usd: default + backfill so building.py cascade can't NoneType ──
ALTER TABLE goals ALTER COLUMN max_cost_usd SET DEFAULT 5.00;
UPDATE goals SET max_cost_usd = 5.00 WHERE max_cost_usd IS NULL AND status = 'active';
