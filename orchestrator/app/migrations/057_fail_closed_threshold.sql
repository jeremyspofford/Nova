-- Migration 057: AQ-003 — Shift default pod.escalation_threshold from 'high' to 'medium'.
--
-- Fail-closed posture: a guardrail block with medium-severity findings should
-- pause for human review, not ship the tainted output. Remediable findings
-- (prompt_injection, pii_exposure, credential_leak) are handled by the new
-- guardrail refactor loop in executor.py before this threshold check fires,
-- so this scalar now only governs non-remediable types (jailbreak attempts,
-- topic drift, spec violations) where medium is the correct conservative bar.
--
-- Idempotency:
--   - ALTER COLUMN SET DEFAULT is idempotent on Postgres (re-running is a no-op).
--   - The UPDATE is guarded by is_system_default = true AND the row's
--     updated_at matches its created_at — i.e. the row has never been
--     user-modified. User-customized pods are never touched.
--   - Wrapped in DO $$ ... $$ so the whole block is safe to re-run.

DO $$
BEGIN
    -- 1. New pods default to medium
    ALTER TABLE pods ALTER COLUMN escalation_threshold SET DEFAULT 'medium';

    -- 2. System-default pods still on 'high' that have never been edited
    --    are migrated to 'medium'. We compare updated_at = created_at because
    --    the base schema backfills both to now() on row insert; any subsequent
    --    UPDATE (via dashboard or PATCH /api/v1/pods/{id}) advances updated_at
    --    and excludes the row from the migration.
    UPDATE pods
       SET escalation_threshold = 'medium',
           updated_at = now()
     WHERE is_system_default = true
       AND escalation_threshold = 'high'
       AND updated_at = created_at;
END $$;
