-- Migration 054: Ensure synthetic admin user exists for local/trusted-network sessions
-- When REQUIRE_AUTH=false or on a trusted network, the auth layer returns a synthetic
-- admin with this UUID. Conversations need a real FK target in the users table.

INSERT INTO users (id, email, display_name, provider, is_admin)
VALUES (
    '00000000-0000-0000-0000-000000000000',
    'admin@local',
    'Admin',
    'local',
    TRUE
)
ON CONFLICT (id) DO NOTHING;
