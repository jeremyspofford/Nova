-- Migration 026: Parallelize Guardrail + Code Review stages
-- Phase 4b Step 2: Both are independent assessments of the Task Agent's output,
-- so they can run concurrently within a parallel group.
-- The executor's post-group logic handles flag-setting and refactor loops.
-- Idempotent: UPDATE with WHERE clause (no-op if already set).

UPDATE pod_agents
SET parallel_group = 'review',
    updated_at = now()
WHERE role IN ('guardrail', 'code_review')
  AND (parallel_group IS NULL OR parallel_group != 'review');
