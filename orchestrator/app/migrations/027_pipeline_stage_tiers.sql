-- 027: Right-size models per pipeline stage for performance (Phase 4b)
--
-- Context Agent just reads files and curates context — a cheap/fast model
-- is sufficient and significantly reduces cost + latency.
--
-- Code Review Agent performs quality assessment — mid-tier balances
-- accuracy with cost savings vs. using the best model.
--
-- Task, Guardrail, and Decision agents are left unchanged (they inherit
-- from the pod default or the _STAGE_TIER_MAP in the executor).
--
-- The "tier:<name>" syntax is resolved by the pipeline executor:
-- it strips the prefix, sets model=NULL (so the gateway's tier resolver
-- picks the best available model at that tier), and passes the tier
-- as a routing hint.
--
-- Idempotent: only updates rows where model is currently NULL (default
-- pod agents that haven't been customised by the user).

UPDATE pod_agents SET model = 'tier:cheap', updated_at = now()
WHERE role = 'context' AND model IS NULL;

UPDATE pod_agents SET model = 'tier:mid', updated_at = now()
WHERE role = 'code_review' AND model IS NULL;
