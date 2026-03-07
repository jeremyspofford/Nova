---
title: "Memory Service"
description: "Embedding generation and hybrid semantic/keyword retrieval via pgvector. Port 8002."
---

The Memory Service provides Nova's long-term memory system. It stores, retrieves, and manages memories across three tiers using PostgreSQL with pgvector for embedding-based similarity search combined with full-text keyword matching.

## At a glance

| Property | Value |
|----------|-------|
| **Port** | 8002 |
| **Framework** | FastAPI + SQLAlchemy async |
| **Database** | PostgreSQL 16 with pgvector |
| **State store** | Redis (db 0) |
| **Source** | `memory-service/` |

## Memory tiers

| Tier | Purpose | Storage |
|------|---------|---------|
| **Semantic** | Facts with confidence decay -- key-value knowledge that ages using ACT-R cognitive model | PostgreSQL + pgvector embeddings |
| **Procedural** | Lessons learned and procedures -- how to do things | PostgreSQL + pgvector embeddings |
| **Episodic** | Task summaries and event records -- what happened | PostgreSQL + pgvector embeddings |

## Key responsibilities

- **Memory storage** -- store text content with embeddings across all three tiers
- **Hybrid retrieval** -- combine 70% cosine similarity (vector) with 30% ts_rank (full-text keyword) for accurate search
- **Fact management** -- upsert facts keyed on `(project_id, category, key)` with confidence tracking
- **Context assembly** -- build agent context packages from relevant memories for a given query
- **Confidence decay** -- ACT-R power-law decay: `effective_confidence = base_confidence * (days_since_access ^ -0.5)`
- **Background maintenance** -- cleanup of expired working memories, memory compaction, and table partitioning

## Key endpoints

All memory endpoints are prefixed with `/api/v1/memories`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/memories` | Store a new memory (auto-embeds content) |
| POST | `/api/v1/memories/search` | Hybrid semantic + keyword search |
| POST | `/api/v1/memories/facts` | Save or upsert a fact |
| POST | `/api/v1/memories/bulk` | Bulk store multiple memories |
| GET | `/api/v1/memories/browse` | Browse memories with pagination and tier filter |
| GET | `/api/v1/memories/{id}` | Get a specific memory |
| PATCH | `/api/v1/memories/{id}` | Update a memory |
| DELETE | `/api/v1/memories/{id}` | Delete a memory |
| POST | `/api/v1/memories/{agent_id}/context` | Build context package for an agent |

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe (checks DB) |

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | -- |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/0` |
| `LLM_GATEWAY_URL` | URL of the LLM Gateway for embeddings | `http://llm-gateway:8001` |
| `LOG_LEVEL` | Logging level | `INFO` |

## Embedding pipeline

The Memory Service generates embeddings via the LLM Gateway's `/embed` endpoint. The embedding fallback chain is:

1. **`text-embedding-3-small`** (OpenAI) -- 1536 dimensions
2. **`nomic-embed-text`** (Ollama) -- 768 dimensions, zero-padded to 1536 for compatibility

A 3-tier embedding cache reduces redundant embedding calls:
- **L1**: Redis (fast, volatile)
- **L2**: PostgreSQL (persistent)
- **L3**: LLM Gateway (source of truth)

## Background tasks

Three background loops run continuously:

| Task | Interval | Purpose |
|------|----------|---------|
| **Cleanup** | Every 5 minutes | Delete expired working memory rows |
| **Compaction** | Configurable | Merge and consolidate related memories |
| **Partitioning** | Configurable | Manage table partitions for performance |

## Implementation notes

- **SQLAlchemy async** -- unlike the Orchestrator (which uses raw asyncpg), Memory Service uses SQLAlchemy's async engine for ORM-style queries
- **Hybrid search** -- combines pgvector cosine similarity with PostgreSQL full-text search (`ts_rank`) in a single query for best results on both semantic and exact-match lookups
- **ACT-R confidence** -- the cognitive science-based decay model ensures stale facts naturally lose relevance over time, preventing outdated information from contaminating agent context
- **Schema migrations** -- run automatically at startup via `run_schema_migrations()`
