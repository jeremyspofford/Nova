-- Phase 4 completion: add Critique + post-pipeline agents to Quartet pod
-- Idempotent: ON CONFLICT DO NOTHING

-- Shift existing agents to make room for Critique agents
-- New order: Context(1), Task(2), Critique-Direction(3), Guardrail(4), Code Review(5), Critique-Acceptance(6), Decision(7)
UPDATE pod_agents SET position = 7 WHERE role = 'decision'     AND pod_id = (SELECT id FROM pods WHERE name = 'Quartet') AND position = 5;
UPDATE pod_agents SET position = 5 WHERE role = 'code_review'  AND pod_id = (SELECT id FROM pods WHERE name = 'Quartet') AND position = 4;
UPDATE pod_agents SET position = 4 WHERE role = 'guardrail'    AND pod_id = (SELECT id FROM pods WHERE name = 'Quartet') AND position = 3;

-- Insert Critique agents
INSERT INTO pod_agents (pod_id, name, role, description, position, temperature, max_tokens, timeout_seconds, max_retries, on_failure, run_condition)
SELECT p.id, a.name, a.role, a.description, a.position, a.temperature, a.max_tokens, a.timeout_seconds, a.max_retries, a.on_failure, a.run_condition::jsonb
FROM pods p
CROSS JOIN (VALUES
    ('Critique-Direction', 'critique_direction', 'Direction gate: is the output attempting the right thing?', 3, 0.2, 4096, 60, 2, 'escalate', '{"type":"not_flag","flag":"critique_approved"}'),
    ('Critique-Acceptance', 'critique_acceptance', 'Acceptance test: does the output fulfill the original request?', 6, 0.2, 4096, 60, 1, 'escalate', '{"type":"always"}')
) AS a(name, role, description, position, temperature, max_tokens, timeout_seconds, max_retries, on_failure, run_condition)
WHERE p.name = 'Quartet'
ON CONFLICT (pod_id, position) DO NOTHING;
