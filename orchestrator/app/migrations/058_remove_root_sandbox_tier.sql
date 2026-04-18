-- Migration 058: SEC-001 — Remove `root` sandbox tier from stored state.
--
-- The `root` tier granted full host filesystem access via the /:/host-root:rw
-- Docker mount. That combo was an RCE-by-design configuration: any prompt
-- injection reaching an agent in this tier could rewrite arbitrary host
-- files. The tier has been deleted from the SandboxTier enum, the mount
-- has been dropped from docker-compose, and existing stored state must be
-- normalized to a safe value.
--
-- Policy: any row referencing the removed tier is rewritten to `workspace`
-- (the safest default — bind-mount isolated from the host). Users who
-- previously relied on root-tier behavior will need to opt into the `home`
-- tier via the Dashboard (Settings → Security → Sandbox) and enable the
-- explicit admin toggle.
--
-- Idempotency: the WHERE clauses only match the (now-illegal) 'root' values.
-- Re-running the migration after the first successful run is a no-op.

DO $$
BEGIN
    -- 1. Normalize pod.sandbox rows.
    UPDATE pods
       SET sandbox = 'workspace',
           updated_at = now()
     WHERE sandbox = 'root';

    -- 2. Normalize the platform-wide default (shell.sandbox in platform_config).
    --    Stored as a JSONB string: '"root"' or '"workspace"'.
    UPDATE platform_config
       SET value = '"workspace"'::jsonb
     WHERE key = 'shell.sandbox'
       AND value::text IN ('"root"', '"host"');

    -- 3. Ensure the new admin opt-in toggle exists with a safe default.
    --    (home tier is now gated behind sandbox.home_enabled = 'true'.)
    INSERT INTO platform_config (key, value, updated_at)
    VALUES ('sandbox.home_enabled', 'false'::jsonb, now())
    ON CONFLICT (key) DO NOTHING;
END $$;
