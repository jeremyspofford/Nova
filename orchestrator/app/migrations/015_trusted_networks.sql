-- 015: Seed platform_config with trusted network settings
INSERT INTO platform_config (key, value, description, is_secret)
VALUES
  ('trusted_networks', '"127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,::1/128"',
   'Comma-separated CIDRs that bypass auth (treated as admin). Includes private networks, Tailscale CGNAT, and localhost. Set to empty string to disable.', false),
  ('trusted_proxy_header', '""',
   'HTTP header containing real client IP when behind a reverse proxy (e.g. CF-Connecting-IP, X-Real-IP). Leave empty if not behind a proxy.', false)
ON CONFLICT (key) DO NOTHING;
