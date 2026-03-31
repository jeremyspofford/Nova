-- Rename sandbox tier values: nova → home, host → root
-- The SandboxTier enum's _missing_() method handles backward compat in code,
-- but we also update stored values so the DB reflects current names.

-- Global sandbox tier setting (key: shell.sandbox, value: bare JSON string)
UPDATE platform_config
SET value = '"home"'::jsonb, updated_at = NOW()
WHERE key = 'shell.sandbox' AND value #>> '{}' = 'nova';

UPDATE platform_config
SET value = '"root"'::jsonb, updated_at = NOW()
WHERE key = 'shell.sandbox' AND value #>> '{}' = 'host';

-- Update migration 037 description to reflect new tier names
UPDATE platform_config
SET description = 'Agent filesystem access tier: workspace (user projects), home (home directory), root (full host), isolated (no access)'
WHERE key = 'shell.sandbox';

-- Pod-level sandbox configs (stored in pods.config JSONB)
UPDATE pods
SET config = jsonb_set(config, '{sandbox}', '"home"')
WHERE config->>'sandbox' = 'nova';

UPDATE pods
SET config = jsonb_set(config, '{sandbox}', '"root"')
WHERE config->>'sandbox' = 'host';
