-- Audit log for platform_config changes (tool permissions, etc.)
-- Tracks who changed what and when for compliance and debugging.

CREATE TABLE IF NOT EXISTS platform_config_audit (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key  TEXT NOT NULL,
    old_value   JSONB,
    new_value   JSONB,
    changed_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_config_audit_key_time
    ON platform_config_audit (config_key, changed_at DESC);
