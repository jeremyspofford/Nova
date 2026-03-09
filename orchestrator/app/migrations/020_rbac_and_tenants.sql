-- 019: RBAC schema and tenant scaffolding
-- Adds role-based access control, tenant isolation scaffolding, and audit logging.

-- 1. Tenants table
CREATE TABLE IF NOT EXISTS tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_by  UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed default tenant
INSERT INTO tenants (id, name) VALUES
    ('00000000-0000-0000-0000-000000000001', 'Default')
ON CONFLICT (id) DO NOTHING;

-- 2. Users table — add RBAC columns
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'role') THEN
        ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'tenant_id') THEN
        ALTER TABLE users ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'expires_at') THEN
        ALTER TABLE users ADD COLUMN expires_at TIMESTAMPTZ;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'status') THEN
        ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
    END IF;
END $$;

-- 3. Backfill roles from is_admin
DO $$ BEGIN
    -- First admin by created_at becomes owner
    UPDATE users SET role = 'owner'
    WHERE id = (SELECT id FROM users WHERE is_admin = true ORDER BY created_at ASC LIMIT 1)
      AND role = 'member';

    -- Other admins become admin
    UPDATE users SET role = 'admin'
    WHERE is_admin = true AND role = 'member';
END $$;

-- 4. Invite codes — add RBAC columns
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'invite_codes' AND column_name = 'role') THEN
        ALTER TABLE invite_codes ADD COLUMN role TEXT NOT NULL DEFAULT 'member';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'invite_codes' AND column_name = 'account_expires_in_hours') THEN
        ALTER TABLE invite_codes ADD COLUMN account_expires_in_hours INTEGER;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'invite_codes' AND column_name = 'tenant_id') THEN
        ALTER TABLE invite_codes ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants(id);
    END IF;
END $$;

-- 5. Tenant scaffolding on data tables
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'conversations' AND column_name = 'tenant_id') THEN
        ALTER TABLE conversations ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'api_keys' AND column_name = 'tenant_id') THEN
        ALTER TABLE api_keys ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'usage_events' AND column_name = 'tenant_id') THEN
        ALTER TABLE usage_events ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants(id);
    END IF;
END $$;

-- 6. RBAC audit log (separate from the operational audit_log table)
CREATE TABLE IF NOT EXISTS rbac_audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id    UUID REFERENCES users(id),
    action      TEXT NOT NULL,
    target_id   UUID,
    details     JSONB,
    ip_address  TEXT,
    tenant_id   UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rbac_audit_log_tenant ON rbac_audit_log(tenant_id, created_at DESC);

-- 7. Guest allowed models config
INSERT INTO platform_config (key, value, description, is_secret) VALUES
    ('guest_allowed_models', '[]'::jsonb, 'Models available to guest (unauthenticated) users. Empty array = no guest access.', false)
ON CONFLICT (key) DO NOTHING;
