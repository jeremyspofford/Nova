-- 025: Seed inference.backend config key for managed inference backends

INSERT INTO platform_config (key, value, description)
VALUES ('inference.backend', '"ollama"', 'Active local inference backend (ollama or vllm)')
ON CONFLICT (key) DO NOTHING;
