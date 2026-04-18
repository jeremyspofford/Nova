-- 059: Remove Claude subscription OAuth references from platform_config.
-- Anthropic's 2026-02 ToS update prohibits third-party use of sk-ant-oat01-*
-- OAuth tokens outside the official Claude CLI, so Nova no longer ships the
-- Claude Max/Pro subscription provider. Existing installs keep their routing
-- map intact for non-claude-max entries but lose the offending IDs.

UPDATE platform_config
SET value = '{"general":null,"code":["claude-sonnet-4-6","gpt-4o","chatgpt/gpt-4o"],"reasoning":["chatgpt/o3","chatgpt/o4-mini","claude-sonnet-4-6"],"creative":["claude-sonnet-4-6","gpt-4o"],"quick":["groq/llama-3.3-70b-versatile","cerebras/llama3.1-8b","gemini/gemini-2.5-flash"]}'
WHERE key = 'llm.model_routing_map'
  AND value::text LIKE '%claude-max%';
