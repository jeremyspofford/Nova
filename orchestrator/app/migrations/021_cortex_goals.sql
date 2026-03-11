-- 021: Cortex foundation — goals, cortex_state, system user, API key, journal conversation

-- ── Goals table ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS goals (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title                   TEXT NOT NULL,
    description             TEXT,
    status                  TEXT NOT NULL DEFAULT 'active',
        -- active, paused, completed, failed, cancelled
    priority                INTEGER NOT NULL DEFAULT 0,
    progress                REAL NOT NULL DEFAULT 0.0,
    current_plan            JSONB,
    iteration               INTEGER NOT NULL DEFAULT 0,
    max_iterations          INTEGER DEFAULT 50,
    max_cost_usd            REAL,
    cost_so_far_usd         REAL NOT NULL DEFAULT 0.0,
    check_interval_seconds  INTEGER DEFAULT 3600,
    last_checked_at         TIMESTAMPTZ,
    parent_goal_id          UUID REFERENCES goals(id),
    created_by              TEXT NOT NULL DEFAULT 'user',
    tenant_id               UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS goals_status_idx ON goals(status);
CREATE INDEX IF NOT EXISTS goals_priority_idx ON goals(priority DESC) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS goals_tenant_idx ON goals(tenant_id);
CREATE INDEX IF NOT EXISTS goals_parent_idx ON goals(parent_goal_id) WHERE parent_goal_id IS NOT NULL;

-- ── Goal-to-task mapping ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS goal_tasks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id     UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    task_id     UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    sequence    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(goal_id, task_id)
);

CREATE INDEX IF NOT EXISTS goal_tasks_goal_idx ON goal_tasks(goal_id);

-- ── Add FK on existing tasks.goal_id → goals ────────────────────────────────
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tasks_goal_id_fkey'
    ) THEN
        ALTER TABLE tasks ADD CONSTRAINT tasks_goal_id_fkey
            FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE SET NULL;
    END IF;
END $$;

-- ── Cortex singleton state ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cortex_state (
    id              BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    status          TEXT NOT NULL DEFAULT 'running',
    current_drive   TEXT,
    cycle_count     BIGINT NOT NULL DEFAULT 0,
    last_cycle_at   TIMESTAMPTZ,
    last_checkpoint JSONB,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO cortex_state DEFAULT VALUES ON CONFLICT DO NOTHING;

-- ── System user for Cortex ───────────────────────────────────────────────────
INSERT INTO users (id, email, display_name, role, status, created_at)
VALUES (
    'a0000000-0000-0000-0000-000000000001',
    'cortex@system.nova',
    'Cortex',
    'owner',
    'active',
    NOW()
) ON CONFLICT (email) DO NOTHING;

-- ── Cortex API key (deterministic hash so it's idempotent) ───────────────────
-- Key value: sk-nova-cortex-internal (never exposed externally)
INSERT INTO api_keys (id, name, key_hash, key_prefix, is_active, rate_limit_rpm, metadata)
VALUES (
    'b0000000-0000-0000-0000-000000000001',
    'cortex-internal',
    encode(sha256('sk-nova-cortex-internal'::bytea), 'hex'),
    'sk-nova-cortex',
    TRUE,
    600,
    '{"system": true, "owner": "cortex"}'::jsonb
) ON CONFLICT (id) DO NOTHING;

-- ── Journal conversation for Cortex ──────────────────────────────────────────
INSERT INTO conversations (id, title, user_id, created_at)
VALUES (
    'c0000000-0000-0000-0000-000000000001',
    'Cortex Journal',
    'a0000000-0000-0000-0000-000000000001',
    NOW()
) ON CONFLICT (id) DO NOTHING;
