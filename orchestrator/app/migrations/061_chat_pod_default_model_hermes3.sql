-- 061: Set chat-default pod's agent model to hermes3:8b when unset.
--
-- Context (companion to migration 060): the chat pod's agent configuration in
-- pod_agents is what resolves for the chat UI's model selection, not the
-- agent.config.model field. Without an explicit pod_agents.model, chat falls
-- back to DEFAULT_CHAT_MODEL from .env — which is typically qwen2.5:7b.
--
-- qwen2.5:7b hits tool-paralysis on the full 52+ tool catalog. Hermes 3 8B is
-- community-built for function calling and handles the full catalog cleanly
-- on an 8GB VRAM budget (same 4.7GB footprint as qwen2.5:7b).
--
-- Migration 060 added a conservative disabled_groups list to make qwen2.5:7b
-- workable. This migration sets the model that makes those restrictions
-- unnecessary — users can then widen the tool catalog from the dashboard.
--
-- Idempotent + non-destructive: only sets the model when it's currently NULL
-- or empty. Users with a custom model are untouched.

UPDATE pod_agents pa
SET model = 'hermes3:8b'
FROM pods p
WHERE pa.pod_id = p.id
  AND p.is_chat_default = true
  AND (pa.model IS NULL OR pa.model = '');
