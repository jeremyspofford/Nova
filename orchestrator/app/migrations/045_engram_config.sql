-- Engram memory system configuration (UI-manageable via Settings page)
INSERT INTO platform_config (key, value, description, is_secret)
VALUES
    ('engram.decomposition_model', '"auto"',
     'Model for memory decomposition. "auto" probes local models. Recommended: groq/llama-3.3-70b-versatile (cloud) or qwen2.5:7b (local)',
     false)
ON CONFLICT (key) DO NOTHING;
