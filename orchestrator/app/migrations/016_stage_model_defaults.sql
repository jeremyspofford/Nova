-- 016: Per-stage model defaults for pipeline
-- Allows configuring different models for each pipeline stage.

INSERT INTO platform_config (key, value) VALUES
    ('pipeline.stage_defaults_enabled', '"false"'::jsonb),
    ('pipeline.stage_model.context',    'null'::jsonb),
    ('pipeline.stage_model.task',       'null'::jsonb),
    ('pipeline.stage_model.guardrail',  'null'::jsonb),
    ('pipeline.stage_model.code_review', 'null'::jsonb),
    ('pipeline.stage_model.decision',   'null'::jsonb)
ON CONFLICT (key) DO NOTHING;
