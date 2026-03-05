-- Migration 008: Seed context budget defaults into platform_config
--
-- These control how the orchestrator allocates the context window across
-- different content categories. Values are fractions (0.0–1.0) and should
-- sum to 1.0 for the five budget slices.

INSERT INTO platform_config (key, value, description) VALUES
    (
        'context.system_pct',
        '0.10',
        'Fraction of context window reserved for the system prompt'
    ),
    (
        'context.tools_pct',
        '0.15',
        'Fraction of context window reserved for tool definitions and results'
    ),
    (
        'context.memory_pct',
        '0.40',
        'Fraction of context window reserved for retrieved memories'
    ),
    (
        'context.history_pct',
        '0.20',
        'Fraction of context window reserved for conversation history'
    ),
    (
        'context.working_pct',
        '0.15',
        'Fraction of context window reserved for working/scratch content'
    ),
    (
        'context.compaction_threshold',
        '0.80',
        'Trigger context compaction when total usage exceeds this fraction of the context window'
    )
ON CONFLICT (key) DO NOTHING;
