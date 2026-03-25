-- Migration 041: Knowledge sources schema
-- Tables for user-defined knowledge sources (web crawl, social profiles, manual import),
-- credential management, crawl logging, page caching, and credential audit trail.

CREATE TABLE IF NOT EXISTS knowledge_credentials (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL,
    provider          TEXT NOT NULL DEFAULT 'builtin'
                      CHECK (provider IN ('builtin', 'vault', 'onepassword', 'bitwarden')),
    label             TEXT NOT NULL,
    encrypted_data    BYTEA,
    external_ref      TEXT,
    key_version       INTEGER NOT NULL DEFAULT 1,
    scopes            JSONB,
    last_validated_at TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_credentials_tenant
    ON knowledge_credentials(tenant_id);

CREATE TABLE IF NOT EXISTS knowledge_sources (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    name                TEXT NOT NULL,
    source_type         TEXT NOT NULL
                        CHECK (source_type IN (
                            'web_crawl', 'github_profile', 'gitlab_profile',
                            'twitter', 'mastodon', 'bluesky', 'reddit_profile',
                            'manual_import'
                        )),
    url                 TEXT NOT NULL,
    scope               TEXT NOT NULL DEFAULT 'personal'
                        CHECK (scope IN ('personal', 'shared')),
    crawl_config        JSONB NOT NULL DEFAULT '{}',
    credential_id       UUID REFERENCES knowledge_credentials(id) ON DELETE SET NULL,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'paused', 'error', 'restricted')),
    last_crawl_at       TIMESTAMPTZ,
    last_crawl_summary  JSONB,
    error_count         INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_sources_tenant ON knowledge_sources(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_sources_status ON knowledge_sources(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_sources_scope ON knowledge_sources(scope);

CREATE TABLE IF NOT EXISTS knowledge_crawl_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    source_id       UUID NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    pages_visited   INTEGER NOT NULL DEFAULT 0,
    pages_skipped   INTEGER NOT NULL DEFAULT 0,
    engrams_created INTEGER NOT NULL DEFAULT 0,
    engrams_updated INTEGER NOT NULL DEFAULT 0,
    llm_calls_made  INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    error_detail    TEXT,
    crawl_tree      JSONB
);

CREATE INDEX IF NOT EXISTS idx_knowledge_crawl_log_source ON knowledge_crawl_log(source_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_crawl_log_tenant ON knowledge_crawl_log(tenant_id);

CREATE TABLE IF NOT EXISTS knowledge_page_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    source_id       UUID NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,
    content_hash    TEXT,
    last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_id, url)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_page_cache_source ON knowledge_page_cache(source_id);

CREATE TABLE IF NOT EXISTS knowledge_credential_audit (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    credential_id   UUID NOT NULL REFERENCES knowledge_credentials(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL,
    action          TEXT NOT NULL
                    CHECK (action IN ('retrieve', 'store', 'rotate', 'delete', 'validate')),
    actor           TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    success         BOOLEAN NOT NULL DEFAULT true,
    detail          TEXT
);

CREATE INDEX IF NOT EXISTS idx_knowledge_credential_audit_cred
    ON knowledge_credential_audit(credential_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_credential_audit_tenant
    ON knowledge_credential_audit(tenant_id);
