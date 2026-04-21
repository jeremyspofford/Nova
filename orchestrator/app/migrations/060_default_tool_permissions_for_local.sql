-- 060: Default tool_permissions config tuned for local 7B models.
--
-- Context: small local models (qwen2.5:7b on 8GB VRAM) exhibit "tool paralysis"
-- when presented with more than ~30 tool definitions — they emit zero tool_calls
-- AND empty content, effectively bricking Nova's tool-use in chat. Without any
-- tool_permissions config, the effective tool set includes 10 built-in groups
-- (52 tools) plus any connected MCP servers (firecrawl=12, puppeteer=7 = 71 total).
--
-- This migration seeds a sensible default that keeps ~25–30 tools visible to the
-- chat model, which is below the paralysis threshold we measured. Users with
-- larger models (Hermes 3 8B, qwen3.5:9b, any API model) can widen this from
-- the dashboard without penalty.
--
-- Idempotent: only inserts if no tool_permissions config already exists, so
-- we don't trample user-customized settings on re-run or upgrade.

INSERT INTO platform_config (key, value)
VALUES (
  'tool_permissions',
  '{"disabled_groups": ["MCP: firecrawl", "MCP: puppeteer", "Intel", "Config", "GitHub", "Diagnosis"]}'::jsonb
)
ON CONFLICT (key) DO NOTHING;
