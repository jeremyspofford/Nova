-- 017: Complexity-based model routing for pipeline
-- Classifies tasks as simple/moderate/complex and routes to appropriate models.

INSERT INTO platform_config (key, value) VALUES
    ('pipeline.complexity_routing_enabled',      '"false"'::jsonb),
    ('pipeline.complexity_model_map',            '{}'::jsonb),
    ('pipeline.complexity_classifier_timeout_ms', '"500"'::jsonb)
ON CONFLICT (key) DO NOTHING;
