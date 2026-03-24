-- Sandbox tier config — controls agent filesystem access scope
INSERT INTO platform_config (key, value, description, is_secret)
VALUES ('shell.sandbox', '"workspace"', 'Agent filesystem access tier: workspace (user projects), nova (self-modification), host (full system), isolated (no access)', false)
ON CONFLICT (key) DO NOTHING;
