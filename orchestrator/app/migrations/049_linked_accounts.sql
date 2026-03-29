-- 049_linked_accounts.sql
-- Maps external platform identities to Nova users for cross-channel chat unification.

CREATE TABLE IF NOT EXISTS linked_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform        TEXT NOT NULL,
    platform_id     TEXT NOT NULL,
    platform_username TEXT,
    linked_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One link per platform per user
CREATE UNIQUE INDEX IF NOT EXISTS uq_linked_accounts_user_platform
    ON linked_accounts (user_id, platform);

-- One platform identity maps to exactly one Nova user
CREATE UNIQUE INDEX IF NOT EXISTS uq_linked_accounts_platform_id
    ON linked_accounts (platform, platform_id);
