-- Add agent/pod attribution to usage events for granular cost tracking.
-- Text columns (not FK) so historical records survive renames/deletes.

ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS agent_name TEXT;
ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS pod_name   TEXT;

CREATE INDEX IF NOT EXISTS idx_usage_events_agent_name ON usage_events(agent_name) WHERE agent_name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_usage_events_pod_name   ON usage_events(pod_name)   WHERE pod_name IS NOT NULL;
