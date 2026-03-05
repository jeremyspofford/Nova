-- Phase 3b: Sandbox tiers per pod
-- Adds a sandbox column so operators can restrict filesystem/shell access per pod.
-- Valid values: workspace (default), nova, host, isolated

ALTER TABLE pods ADD COLUMN IF NOT EXISTS sandbox TEXT NOT NULL DEFAULT 'workspace';
