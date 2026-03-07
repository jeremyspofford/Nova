-- 011: Seed default chat model config key for smart auto-detection.
-- "auto" picks the best available model from authenticated providers.

INSERT INTO platform_config (key, value, description) VALUES
  ('llm.default_chat_model', '"auto"', 'Default model for chat and pipeline. "auto" picks best available model.')
ON CONFLICT (key) DO NOTHING;
