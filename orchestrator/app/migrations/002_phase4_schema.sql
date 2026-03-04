-- Migration 002: Phase 4 — Quartet Pipeline, Task Queue, Pod Configuration
-- Idempotent (IF NOT EXISTS / ON CONFLICT DO NOTHING throughout).

-- ── pods ──────────────────────────────────────────────────────────────────────
-- A pod is a named, configurable pipeline of agents.
-- Users can create, clone, enable/disable, and edit pods from the dashboard.

CREATE TABLE IF NOT EXISTS pods (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                     TEXT NOT NULL UNIQUE,
    description              TEXT,
    enabled                  BOOLEAN NOT NULL DEFAULT true,
    default_model            TEXT,
    max_cost_usd             NUMERIC(10, 4),
    max_execution_seconds    INTEGER NOT NULL DEFAULT 300,
    -- 'always' | 'never' | 'on_escalation'
    require_human_review     TEXT NOT NULL DEFAULT 'on_escalation',
    -- 'low' | 'medium' | 'high' | 'critical'
    escalation_threshold     TEXT NOT NULL DEFAULT 'high',
    routing_keywords         TEXT[],
    routing_regex            TEXT,
    priority                 INTEGER NOT NULL DEFAULT 0,
    fallback_pod_id          UUID REFERENCES pods(id),
    -- system defaults cannot be deleted, only disabled
    is_system_default        BOOLEAN NOT NULL DEFAULT false,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── pod_agents ────────────────────────────────────────────────────────────────
-- Each row is one agent slot in a pod's pipeline.
-- position controls execution order. parallel_group allows concurrent execution.

CREATE TABLE IF NOT EXISTS pod_agents (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pod_id           UUID NOT NULL REFERENCES pods(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    -- context | task | guardrail | code_review | decision |
    -- documentation | diagramming | security_review | memory_extraction
    role             TEXT NOT NULL,
    description      TEXT,
    enabled          BOOLEAN NOT NULL DEFAULT true,
    position         INTEGER NOT NULL,
    -- agents sharing a parallel_group run concurrently (post-pipeline cross-cutting agents)
    parallel_group   TEXT,
    -- null inherits pod default_model
    model            TEXT,
    temperature      FLOAT NOT NULL DEFAULT 0.3,
    max_tokens       INTEGER NOT NULL DEFAULT 4096,
    timeout_seconds  INTEGER NOT NULL DEFAULT 60,
    max_retries      INTEGER NOT NULL DEFAULT 1,
    -- null uses the built-in role default
    system_prompt    TEXT,
    task_description TEXT,
    -- null means all tools permitted; [] means no tools
    allowed_tools    TEXT[],
    -- 'skip' | 'abort' | 'escalate'
    on_failure       TEXT NOT NULL DEFAULT 'abort',
    -- e.g. {"type": "always"} or {"type": "on_flag", "flag": "guardrail_blocked"}
    run_condition    JSONB NOT NULL DEFAULT '{"type": "always"}',
    output_schema    JSONB,
    -- code | config | documentation | diagram | decision_record | test | schema | api_contract
    artifact_type    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (pod_id, position)
);

-- ── tasks ─────────────────────────────────────────────────────────────────────
-- Persisted task queue. Every submission creates a row here.
-- The task state machine drives pipeline execution.
--
-- State machine:
--   submitted → queued → {stage}_running → completing → complete
--                                        ↘ pending_human_review (paused)
--                                        ↘ failed
--                                        ↘ cancelled

CREATE TABLE IF NOT EXISTS tasks (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Phase 7 will add goal_id FK once the Goal Layer exists
    goal_id              UUID,
    pod_id               UUID REFERENCES pods(id),
    parent_task_id       UUID REFERENCES tasks(id),

    -- input
    user_input           TEXT NOT NULL,
    api_key_id           UUID REFERENCES api_keys(id) ON DELETE SET NULL,
    model                TEXT,

    -- state machine
    -- submitted | queued | context_running | task_running | guardrail_running |
    -- code_review_running | pending_human_review | completing | complete | failed | cancelled
    status               TEXT NOT NULL DEFAULT 'submitted',
    current_stage        TEXT,     -- which agent role is actively running

    -- failure recovery
    retry_count          INTEGER NOT NULL DEFAULT 0,
    max_retries          INTEGER NOT NULL DEFAULT 2,
    -- running tasks write a heartbeat every 30s; reaper checks this
    last_heartbeat_at    TIMESTAMPTZ,
    -- JSONB map of stage → output saved as each agent completes
    -- e.g. {"context": {...}, "task": {...}}
    -- allows pipeline to resume from last checkpoint instead of restarting
    checkpoint           JSONB NOT NULL DEFAULT '{}',

    -- results
    output               TEXT,
    error                TEXT,
    artifacts            JSONB NOT NULL DEFAULT '[]',

    -- cost roll-up (summed from agent_sessions)
    total_cost_usd       NUMERIC(10, 6) NOT NULL DEFAULT 0,
    total_input_tokens   INTEGER NOT NULL DEFAULT 0,
    total_output_tokens  INTEGER NOT NULL DEFAULT 0,

    -- timing
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    queued_at            TIMESTAMPTZ,
    started_at           TIMESTAMPTZ,
    completed_at         TIMESTAMPTZ,

    metadata             JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS tasks_status_idx    ON tasks(status);
CREATE INDEX IF NOT EXISTS tasks_pod_idx       ON tasks(pod_id);
CREATE INDEX IF NOT EXISTS tasks_created_idx   ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS tasks_goal_idx      ON tasks(goal_id) WHERE goal_id IS NOT NULL;

-- ── agent_sessions ────────────────────────────────────────────────────────────
-- One row per agent invocation within a pipeline run.
-- Enables per-agent cost tracking, heartbeat monitoring, and replay.

CREATE TABLE IF NOT EXISTS agent_sessions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id           UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    pod_agent_id      UUID REFERENCES pod_agents(id) ON DELETE SET NULL,
    role              TEXT NOT NULL,
    position          INTEGER NOT NULL,
    -- pending | running | complete | failed | skipped
    status            TEXT NOT NULL DEFAULT 'pending',
    model             TEXT,
    input_tokens      INTEGER NOT NULL DEFAULT 0,
    output_tokens     INTEGER NOT NULL DEFAULT 0,
    cost_usd          NUMERIC(10, 6) NOT NULL DEFAULT 0,
    -- heartbeat written every 30s while running; reaper kills sessions silent > 2min
    last_heartbeat_at TIMESTAMPTZ,
    output            JSONB,
    error             TEXT,
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    duration_ms       INTEGER
);

CREATE INDEX IF NOT EXISTS agent_sessions_task_idx   ON agent_sessions(task_id);
CREATE INDEX IF NOT EXISTS agent_sessions_status_idx ON agent_sessions(status);

-- ── guardrail_findings ────────────────────────────────────────────────────────
-- Every issue the Guardrail Agent identifies is stored here for audit and review.

CREATE TABLE IF NOT EXISTS guardrail_findings (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id            UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_session_id   UUID REFERENCES agent_sessions(id) ON DELETE SET NULL,
    -- prompt_injection | pii_exposure | credential_leak | spec_drift |
    -- harmful_content | policy_violation | other
    finding_type       TEXT NOT NULL,
    -- low | medium | high | critical
    severity           TEXT NOT NULL,
    description        TEXT NOT NULL,
    evidence           TEXT,
    -- open | acknowledged | resolved | false_positive
    status             TEXT NOT NULL DEFAULT 'open',
    -- 'human' | 'decision_agent' | 'auto'
    resolved_by        TEXT,
    resolution_notes   TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS guardrail_findings_task_idx     ON guardrail_findings(task_id);
CREATE INDEX IF NOT EXISTS guardrail_findings_severity_idx ON guardrail_findings(severity);

-- ── code_reviews ──────────────────────────────────────────────────────────────
-- Each Code Review Agent verdict, including refactor loops.

CREATE TABLE IF NOT EXISTS code_reviews (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id           UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_session_id  UUID REFERENCES agent_sessions(id) ON DELETE SET NULL,
    -- which loop iteration (1 = first review, 2 = after first refactor, etc.)
    iteration         INTEGER NOT NULL DEFAULT 1,
    -- pass | needs_refactor | reject
    verdict           TEXT NOT NULL,
    -- [{severity, description, file, line}]
    issues            JSONB NOT NULL DEFAULT '[]',
    summary           TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS code_reviews_task_idx ON code_reviews(task_id);

-- ── artifacts ─────────────────────────────────────────────────────────────────
-- All outputs produced by agent sessions within a pipeline run.

CREATE TABLE IF NOT EXISTS artifacts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id           UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_session_id  UUID REFERENCES agent_sessions(id) ON DELETE SET NULL,
    -- code | config | documentation | diagram | decision_record |
    -- test | schema | api_contract | context_package
    artifact_type     TEXT NOT NULL,
    name              TEXT NOT NULL,
    content           TEXT NOT NULL,
    content_hash      TEXT,       -- SHA-256 for dedup/change detection
    file_path         TEXT,       -- if written to workspace
    git_commit_sha    TEXT,       -- if committed to git
    metadata          JSONB NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS artifacts_task_idx  ON artifacts(task_id);
CREATE INDEX IF NOT EXISTS artifacts_type_idx  ON artifacts(artifact_type);

-- ── audit_log ─────────────────────────────────────────────────────────────────
-- Immutable BigSerial event log. Never updated, only appended.
-- Captures agent actions, guardrail events, state transitions, human decisions.

CREATE TABLE IF NOT EXISTS audit_log (
    id               BIGSERIAL PRIMARY KEY,
    event_type       TEXT NOT NULL,
    -- debug | info | warning | error | critical
    severity         TEXT NOT NULL DEFAULT 'info',
    task_id          UUID REFERENCES tasks(id) ON DELETE SET NULL,
    agent_session_id UUID REFERENCES agent_sessions(id) ON DELETE SET NULL,
    pod_id           UUID REFERENCES pods(id) ON DELETE SET NULL,
    message          TEXT NOT NULL,
    data             JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_log_task_idx     ON audit_log(task_id) WHERE task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS audit_log_created_idx  ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS audit_log_severity_idx ON audit_log(severity);

-- ─────────────────────────────────────────────────────────────────────────────
-- Default pod seeds
-- Inserted once; users can edit/disable but not delete system defaults.
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO pods (name, description, enabled, require_human_review, escalation_threshold, is_system_default, priority)
VALUES
    ('Quartet',          'Full pipeline: Context → Task → Guardrail → Code Review. Default for all code and config tasks.', true, 'on_escalation', 'high',     true, 100),
    ('Quick Reply',      'Task agent only. No guardrails. For fast, low-stakes queries.',                                    true, 'never',         'critical',  true, 10),
    ('Research',         'Context + Task agents with web search tools. For information gathering, no code output.',         true, 'on_escalation', 'high',     true, 20),
    ('Code Generation',  'Full Quartet with git tools enabled. Auto-commits on Code Review pass.',                          true, 'on_escalation', 'medium',    true, 50),
    ('Analysis',         'Context + Task with read-only tools. For codebase audits, no write operations.',                  true, 'on_escalation', 'high',     true, 30)
ON CONFLICT (name) DO NOTHING;

-- ── Quartet pipeline agents ───────────────────────────────────────────────────

INSERT INTO pod_agents (pod_id, name, role, description, position, model, temperature, max_tokens, timeout_seconds, max_retries, on_failure, run_condition, artifact_type)
SELECT
    p.id,
    a.name, a.role, a.description,
    a.position, a.model, a.temperature, a.max_tokens,
    a.timeout_seconds, a.max_retries, a.on_failure,
    a.run_condition::jsonb, a.artifact_type
FROM pods p
CROSS JOIN (VALUES
    ('Context Agent',     'context',     'Curates relevant code, docs, and project patterns before the Task Agent runs.',       1, NULL,  0.2, 4096, 60,  1, 'abort',    '{"type":"always"}',                                         NULL),
    ('Task Agent',        'task',        'Produces the actual code, config, or answer in a clean context window.',              2, NULL,  0.5, 8192, 120, 3, 'abort',    '{"type":"always"}',                                         'code'),
    ('Guardrail Agent',   'guardrail',   'Checks for prompt injection, PII, credential leaks, and spec drift.',                 3, NULL,  0.1, 2048, 30,  1, 'escalate', '{"type":"always"}',                                         NULL),
    ('Code Review Agent', 'code_review', 'Verdicts: pass / needs_refactor / reject. Loops back to Task Agent on refactor.',    4, NULL,  0.3, 4096, 60,  1, 'escalate', '{"type":"always"}',                                         NULL),
    ('Decision Agent',    'decision',    'Fires when Guardrail blocks AND Code Review rejects. Produces ADR and may escalate.', 5, NULL,  0.2, 4096, 60,  1, 'escalate', '{"type":"and","conditions":[{"type":"on_flag","flag":"guardrail_blocked"},{"type":"on_flag","flag":"code_review_rejected"}]}', 'decision_record')
) AS a(name, role, description, position, model, temperature, max_tokens, timeout_seconds, max_retries, on_failure, run_condition, artifact_type)
WHERE p.name = 'Quartet'
ON CONFLICT (pod_id, position) DO NOTHING;

-- ── Quick Reply agent ─────────────────────────────────────────────────────────

INSERT INTO pod_agents (pod_id, name, role, description, position, temperature, max_tokens, timeout_seconds, on_failure, run_condition)
SELECT p.id, 'Task Agent', 'task', 'Direct LLM response, no pipeline overhead.', 1, 0.5, 4096, 60, 'abort', '{"type":"always"}'
FROM pods p WHERE p.name = 'Quick Reply'
ON CONFLICT (pod_id, position) DO NOTHING;

-- ── Research pipeline agents ──────────────────────────────────────────────────

INSERT INTO pod_agents (pod_id, name, role, description, position, temperature, max_tokens, timeout_seconds, on_failure, run_condition)
SELECT p.id, a.name, a.role, a.description, a.position, a.temperature, a.max_tokens, a.timeout_seconds, a.on_failure, a.run_condition::jsonb
FROM pods p
CROSS JOIN (VALUES
    ('Context Agent', 'context', 'Retrieves relevant prior research and project context.', 1, 0.2, 4096, 60,  'abort', '{"type":"always"}'),
    ('Task Agent',    'task',    'Researches and synthesises an answer.',                  2, 0.7, 8192, 120, 'abort', '{"type":"always"}')
) AS a(name, role, description, position, temperature, max_tokens, timeout_seconds, on_failure, run_condition)
WHERE p.name = 'Research'
ON CONFLICT (pod_id, position) DO NOTHING;

-- ── Code Generation pipeline agents ──────────────────────────────────────────

INSERT INTO pod_agents (pod_id, name, role, description, position, temperature, max_tokens, timeout_seconds, max_retries, on_failure, allowed_tools, run_condition, artifact_type)
SELECT p.id, a.name, a.role, a.description, a.position, a.temperature, a.max_tokens, a.timeout_seconds, a.max_retries, a.on_failure, a.allowed_tools, a.run_condition::jsonb, a.artifact_type
FROM pods p
CROSS JOIN (VALUES
    ('Context Agent',     'context',     'Curates codebase context and project patterns.',              1, 0.2, 4096, 60,  1, 'abort',    NULL,                                                                           '{"type":"always"}', NULL),
    ('Task Agent',        'task',        'Writes the code.',                                            2, 0.5, 8192, 120, 3, 'abort',    ARRAY['list_dir','read_file','write_file','run_shell','search_codebase'],       '{"type":"always"}', 'code'),
    ('Guardrail Agent',   'guardrail',   'Security and spec-drift check.',                             3, 0.1, 2048, 30,  1, 'escalate', ARRAY['read_file','search_codebase'],                                           '{"type":"always"}', NULL),
    ('Code Review Agent', 'code_review', 'Quality verdict. Loops on needs_refactor.',                  4, 0.3, 4096, 60,  1, 'escalate', ARRAY['read_file','search_codebase'],                                           '{"type":"always"}', NULL),
    ('Decision Agent',    'decision',    'ADR + escalation when both Guardrail and Code Review block.', 5, 0.2, 4096, 60,  1, 'escalate', NULL,                                                                           '{"type":"and","conditions":[{"type":"on_flag","flag":"guardrail_blocked"},{"type":"on_flag","flag":"code_review_rejected"}]}', 'decision_record')
) AS a(name, role, description, position, temperature, max_tokens, timeout_seconds, max_retries, on_failure, allowed_tools, run_condition, artifact_type)
WHERE p.name = 'Code Generation'
ON CONFLICT (pod_id, position) DO NOTHING;

-- ── Analysis pipeline agents ──────────────────────────────────────────────────

INSERT INTO pod_agents (pod_id, name, role, description, position, temperature, max_tokens, timeout_seconds, on_failure, allowed_tools, run_condition)
SELECT p.id, a.name, a.role, a.description, a.position, a.temperature, a.max_tokens, a.timeout_seconds, a.on_failure, a.allowed_tools, a.run_condition::jsonb
FROM pods p
CROSS JOIN (VALUES
    ('Context Agent', 'context', 'Scans the codebase for relevant context.',  1, 0.2, 4096, 60,  'abort', ARRAY['list_dir','read_file','search_codebase'], '{"type":"always"}'),
    ('Task Agent',    'task',    'Analyses and reports findings. Read-only.', 2, 0.5, 8192, 120, 'abort', ARRAY['list_dir','read_file','search_codebase'], '{"type":"always"}')
) AS a(name, role, description, position, temperature, max_tokens, timeout_seconds, on_failure, allowed_tools, run_condition)
WHERE p.name = 'Analysis'
ON CONFLICT (pod_id, position) DO NOTHING;
