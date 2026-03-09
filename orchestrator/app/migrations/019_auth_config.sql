-- Auth configuration in platform_config (dynamic, UI-editable)
INSERT INTO platform_config (key, value, description, is_secret, updated_at) VALUES
  ('auth.require_auth', 'true', 'Require authentication for untrusted networks', false, NOW()),
  ('auth.registration_mode', '"invite"', 'User registration mode: invite, open, or admin', false, NOW())
ON CONFLICT (key) DO NOTHING;
