-- 047: Skills and Rules tables
-- Skills: reusable prompt templates injected into agent system prompts
-- Rules: declarative behavior constraints with hard pre-execution enforcement

CREATE TABLE IF NOT EXISTS skills (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'global'
                CHECK (scope IN ('global', 'pod', 'agent')),
    category    TEXT NOT NULL DEFAULT 'custom'
                CHECK (category IN ('workflow', 'coding', 'review', 'safety', 'custom')),
    enabled     BOOLEAN NOT NULL DEFAULT true,
    priority    INTEGER NOT NULL DEFAULT 0,
    is_system   BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rules (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL UNIQUE,
    description  TEXT NOT NULL DEFAULT '',
    rule_text    TEXT NOT NULL,
    enforcement  TEXT NOT NULL DEFAULT 'hard'
                 CHECK (enforcement IN ('soft', 'hard', 'both')),
    pattern      TEXT,
    target_tools TEXT[],
    action       TEXT NOT NULL DEFAULT 'block'
                 CHECK (action IN ('block', 'warn')),
    scope        TEXT NOT NULL DEFAULT 'global'
                 CHECK (scope IN ('global', 'pod', 'agent')),
    category     TEXT NOT NULL DEFAULT 'safety'
                 CHECK (category IN ('safety', 'quality', 'compliance', 'workflow', 'custom')),
    severity     TEXT NOT NULL DEFAULT 'high'
                 CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    enabled      BOOLEAN NOT NULL DEFAULT true,
    is_system    BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO rules (name, description, rule_text, enforcement, pattern, target_tools, action, category, severity, is_system)
VALUES
    ('no-rm-rf', 'Block recursive force delete',
     'Never execute recursive force-delete commands (rm -rf, rm -fr, etc.)',
     'hard', 'rm\s+.*-[rf]{2}', ARRAY['run_shell'], 'block', 'safety', 'critical', true),

    ('workspace-boundary', 'Block operations outside workspace',
     'All file operations must stay within the configured workspace directory',
     'hard', '(^/|\.\./)(?!workspace|tmp|home)', ARRAY['run_shell', 'write_file'], 'block', 'safety', 'high', true),

    ('no-secret-in-output', 'Warn on potential secrets in tool arguments',
     'Flag commands that may contain API keys, passwords, or credentials',
     'hard', '(AKIA[A-Z0-9]{16}|BEGIN\s+(RSA|DSA|EC)\s+PRIVATE|api[_-]?key\s*[:=]\s*\S{20,}|password\s*[:=]\s*\S+)', NULL, 'warn', 'safety', 'critical', true)
ON CONFLICT (name) DO NOTHING;
