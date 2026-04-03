-- Self-modification PR audit trail
CREATE TABLE IF NOT EXISTS selfmod_prs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pr_number     INTEGER NOT NULL,
    branch_name   TEXT NOT NULL,
    title         TEXT NOT NULL,
    body          TEXT DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'open',
    ci_status     TEXT DEFAULT 'pending',
    files_changed INTEGER DEFAULT 0,
    goal_id       UUID,
    task_id       UUID,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    merged_at     TIMESTAMPTZ,
    closed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_selfmod_prs_status ON selfmod_prs(status);

-- Safety rules for self-modification (hard blocks)
-- Split into individual INSERTs for asyncpg extended protocol compatibility
INSERT INTO rules (name, description, rule_text, enforcement, pattern, target_tools, action, category, severity, is_system)
VALUES ('no-push-main', 'Block push to protected branches',
        'Never push directly to main, master, or develop branches',
        'hard', E'(origin\\s+)?(main|master|develop)\\b', ARRAY['github_push_branch', 'run_shell'], 'block', 'safety', 'critical', true)
ON CONFLICT (name) DO NOTHING;

INSERT INTO rules (name, description, rule_text, enforcement, pattern, target_tools, action, category, severity, is_system)
VALUES ('no-force-push', 'Block force push',
        'Never force push any branch',
        'hard', E'--(force|force-with-lease)\\b', ARRAY['github_push_branch', 'run_shell'], 'block', 'safety', 'critical', true)
ON CONFLICT (name) DO NOTHING;

INSERT INTO rules (name, description, rule_text, enforcement, pattern, target_tools, action, category, severity, is_system)
VALUES ('no-merge-pr', 'Block merging pull requests',
        'Nova must never merge its own PRs',
        'hard', E'gh\\s+pr\\s+merge|git\\s+merge\\s+--', ARRAY['run_shell'], 'block', 'safety', 'critical', true)
ON CONFLICT (name) DO NOTHING;

INSERT INTO rules (name, description, rule_text, enforcement, pattern, target_tools, action, category, severity, is_system)
VALUES ('no-direct-main-commit', 'Block commits on main branch',
        'Never commit directly to main',
        'hard', E'git\\s+commit.*\\bmain\\b', ARRAY['run_shell'], 'block', 'safety', 'critical', true)
ON CONFLICT (name) DO NOTHING;
