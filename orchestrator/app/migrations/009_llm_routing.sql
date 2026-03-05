-- 009: LLM routing strategy + Wake-on-LAN config keys
-- These are read by the llm-gateway via Redis (published on update by the orchestrator).

INSERT INTO platform_config (key, value, description) VALUES
  ('llm.routing_strategy', '"local-first"', 'LLM routing: local-only | local-first | cloud-only | cloud-first'),
  ('llm.ollama_url', 'null', 'Remote Ollama base URL (e.g. http://192.168.1.50:11434)'),
  ('llm.cloud_fallback_model', '"groq/llama-3.3-70b-versatile"', 'Cloud model used when Ollama is unavailable'),
  ('llm.cloud_fallback_embed_model', '"text-embedding-004"', 'Cloud embedding model used when Ollama is unavailable'),
  ('llm.wol_mac', 'null', 'MAC address for Wake-on-LAN (e.g. AA:BB:CC:DD:EE:FF)'),
  ('llm.wol_broadcast', '"255.255.255.255"', 'Broadcast IP for Wake-on-LAN packets')
ON CONFLICT (key) DO NOTHING;
