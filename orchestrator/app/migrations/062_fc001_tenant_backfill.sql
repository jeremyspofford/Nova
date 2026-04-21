-- 062: FC-001 — tenant_id backfill shape.
--
-- This migration is a no-op on instances that have always had exactly one
-- user on the default tenant ('00000000-0000-0000-0000-000000000001'), which
-- is every Nova install today. Its purpose is to document and exercise the
-- re-tag pattern so future multi-user migrations have a tested template.
--
-- What it would do on an instance where the first user moved off the default
-- tenant (not currently a supported flow, but possible via manual update):
--   Re-tag every row in engrams / engram_archive / sources / knowledge_*
--   that still carries the seeded default tenant_id so it matches the first
--   user's actual tenant_id — on the assumption that all legacy data was
--   created "for them."
--
-- Multi-user instances (2+ distinct tenant_ids across users) cannot be
-- backfilled automatically — who owns which engram is a human decision. The
-- migration logs a NOTICE and exits without modifying data.

DO $$
DECLARE
    default_tenant UUID := '00000000-0000-0000-0000-000000000001';
    distinct_tenants INT;
    first_user_tenant UUID;
    rows_retagged INT := 0;
BEGIN
    -- How many distinct tenant_ids are in use across the users table?
    SELECT count(DISTINCT tenant_id) INTO distinct_tenants
    FROM users;

    IF distinct_tenants = 0 THEN
        RAISE NOTICE 'FC-001 backfill: no users yet — nothing to re-tag';
        RETURN;
    END IF;

    IF distinct_tenants > 1 THEN
        RAISE NOTICE 'FC-001 backfill: % distinct tenants in use — manual migration required, skipping', distinct_tenants;
        RETURN;
    END IF;

    -- Exactly one tenant across all users. Read it.
    SELECT tenant_id INTO first_user_tenant
    FROM users
    ORDER BY created_at ASC
    LIMIT 1;

    IF first_user_tenant = default_tenant THEN
        RAISE NOTICE 'FC-001 backfill: first user is already on the default tenant — no re-tag needed';
        RETURN;
    END IF;

    -- Only reached when there's exactly one user and their tenant differs
    -- from the seeded default. Re-tag legacy rows still on the default.
    -- NOTE: engrams/sources live in memory-service's schema, which shares the
    -- same database. Orchestrator's migration runner can see them.

    UPDATE engrams
    SET tenant_id = first_user_tenant
    WHERE tenant_id = default_tenant;
    GET DIAGNOSTICS rows_retagged = ROW_COUNT;
    RAISE NOTICE 'FC-001 backfill: re-tagged % engrams to tenant %', rows_retagged, first_user_tenant;

    UPDATE engram_archive
    SET tenant_id = first_user_tenant
    WHERE tenant_id = default_tenant;
    GET DIAGNOSTICS rows_retagged = ROW_COUNT;
    RAISE NOTICE 'FC-001 backfill: re-tagged % engram_archive rows', rows_retagged;

    UPDATE sources
    SET tenant_id = first_user_tenant
    WHERE tenant_id = default_tenant;
    GET DIAGNOSTICS rows_retagged = ROW_COUNT;
    RAISE NOTICE 'FC-001 backfill: re-tagged % sources', rows_retagged;

    UPDATE retrieval_log
    SET tenant_id = first_user_tenant
    WHERE tenant_id = default_tenant;
    GET DIAGNOSTICS rows_retagged = ROW_COUNT;
    RAISE NOTICE 'FC-001 backfill: re-tagged % retrieval_log rows', rows_retagged;

    UPDATE knowledge_sources
    SET tenant_id = first_user_tenant
    WHERE tenant_id = default_tenant;
    GET DIAGNOSTICS rows_retagged = ROW_COUNT;
    RAISE NOTICE 'FC-001 backfill: re-tagged % knowledge_sources', rows_retagged;

    UPDATE knowledge_credentials
    SET tenant_id = first_user_tenant
    WHERE tenant_id = default_tenant;
    GET DIAGNOSTICS rows_retagged = ROW_COUNT;
    RAISE NOTICE 'FC-001 backfill: re-tagged % knowledge_credentials', rows_retagged;

    UPDATE knowledge_crawl_log
    SET tenant_id = first_user_tenant
    WHERE tenant_id = default_tenant;
    GET DIAGNOSTICS rows_retagged = ROW_COUNT;
    RAISE NOTICE 'FC-001 backfill: re-tagged % knowledge_crawl_log rows', rows_retagged;
END $$;
