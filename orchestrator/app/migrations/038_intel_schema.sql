-- Migration 038: Intelligence system schema
-- Tables for feed monitoring, content ingestion, and recommendations

CREATE TABLE IF NOT EXISTS intel_feeds (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  TEXT NOT NULL,
    url                   TEXT NOT NULL,
    feed_type             TEXT NOT NULL CHECK (feed_type IN ('rss', 'reddit_json', 'page', 'github_trending', 'github_releases')),
    category              TEXT,
    check_interval_seconds INTEGER NOT NULL DEFAULT 3600,
    last_checked_at       TIMESTAMPTZ,
    last_hash             TEXT,
    error_count           INTEGER NOT NULL DEFAULT 0,
    enabled               BOOLEAN NOT NULL DEFAULT true,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS intel_content_items (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feed_id       UUID NOT NULL REFERENCES intel_feeds(id) ON DELETE CASCADE,
    content_hash  TEXT NOT NULL UNIQUE,
    title         TEXT,
    url           TEXT,
    body          TEXT,
    author        TEXT,
    score         INTEGER,
    published_at  TIMESTAMPTZ,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata      JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_intel_content_items_feed ON intel_content_items(feed_id);
CREATE INDEX IF NOT EXISTS idx_intel_content_items_ingested ON intel_content_items(ingested_at);

CREATE TABLE IF NOT EXISTS intel_content_items_archive (LIKE intel_content_items INCLUDING ALL);

CREATE TABLE IF NOT EXISTS intel_recommendations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title               TEXT NOT NULL,
    summary             TEXT NOT NULL,
    rationale           TEXT,
    features            TEXT[],
    grade               CHAR(1) NOT NULL CHECK (grade IN ('A', 'B', 'C')),
    confidence          REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    category            TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'speccing', 'review', 'building', 'implemented', 'deferred', 'dismissed')),
    auto_implementable  BOOLEAN NOT NULL DEFAULT false,
    implementation_plan TEXT,
    complexity          TEXT CHECK (complexity IN ('low', 'medium', 'high')),
    goal_id             UUID REFERENCES goals(id),
    task_id             UUID,
    dismissed_hash_cluster TEXT[],
    decided_by          TEXT,
    decided_at          TIMESTAMPTZ,
    implemented_at      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_intel_recommendations_status ON intel_recommendations(status);
CREATE INDEX IF NOT EXISTS idx_intel_recommendations_grade ON intel_recommendations(grade);
CREATE INDEX IF NOT EXISTS idx_intel_recommendations_dismissed_hashes ON intel_recommendations USING GIN (dismissed_hash_cluster) WHERE status = 'dismissed';

CREATE TABLE IF NOT EXISTS intel_recommendation_sources (
    recommendation_id UUID NOT NULL REFERENCES intel_recommendations(id) ON DELETE CASCADE,
    content_item_id   UUID NOT NULL REFERENCES intel_content_items(id) ON DELETE CASCADE,
    relevance_note    TEXT,
    PRIMARY KEY (recommendation_id, content_item_id)
);

CREATE TABLE IF NOT EXISTS intel_recommendation_engrams (
    recommendation_id UUID NOT NULL REFERENCES intel_recommendations(id) ON DELETE CASCADE,
    engram_id         UUID NOT NULL,
    activation_score  REAL,
    PRIMARY KEY (recommendation_id, engram_id)
);
