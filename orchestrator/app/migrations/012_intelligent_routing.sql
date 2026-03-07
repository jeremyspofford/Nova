-- 012: Intelligent model routing — classifier picks optimal model per message.
-- Ships disabled by default (opt-in via Settings).

INSERT INTO platform_config (key, value, description, is_secret) VALUES
  ('llm.intelligent_routing', 'true',
   'Enable intelligent model routing — classifier picks optimal model per message', false),
  ('llm.classifier_model', '"auto"',
   'Classifier model: "auto" (local-first) or explicit model ID', false),
  ('llm.model_routing_map',
   '{"general":null,"code":["claude-sonnet-4-6","claude-max/claude-sonnet-4-6","gpt-4o","chatgpt/gpt-4o"],"reasoning":["chatgpt/o3","chatgpt/o4-mini","claude-sonnet-4-6"],"creative":["claude-sonnet-4-6","gpt-4o"],"quick":["groq/llama-3.3-70b-versatile","cerebras/llama3.1-8b","gemini/gemini-2.5-flash"]}',
   'Category-to-model preference mapping (JSON). null = use default auto-resolve.', false),
  ('llm.classifier_timeout_ms', '500',
   'Max milliseconds to wait for classifier response', false)
ON CONFLICT (key) DO NOTHING;
