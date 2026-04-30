-- Brain feature flag — controls Cortex's autonomous thinking loop AND the
-- dashboard's engram graph prefetch + 3D visualization keep-alive.
--
-- Default: OFF. Both consumers are resource-heavy (continuous local LLM calls,
-- a 2,000-node graph fetch on every dashboard load). New installs should opt
-- in via /settings#brain after confirming their host has the headroom.
--
-- Supersedes the unused 'features.cortex_loop' from migration 056.
INSERT INTO platform_config (key, value, updated_at)
VALUES ('features.brain_enabled', 'false'::jsonb, NOW())
ON CONFLICT (key) DO NOTHING;

-- Remove the dead flag so the dashboard config view doesn't show a phantom
-- toggle that nothing reads.
DELETE FROM platform_config WHERE key = 'features.cortex_loop';
