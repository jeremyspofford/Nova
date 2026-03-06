-- Add metadata column to pods table (referenced by create_pod but missing from schema)
ALTER TABLE pods ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';
