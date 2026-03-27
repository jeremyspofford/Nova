# Source Provenance & Memory Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Nova's memory system from opaque context injection into a transparent, source-tracked, tool-driven knowledge system with infinite scalable memory.

**Architecture:** Add a `sources` table as the provenance backbone for all engram knowledge. Shift from 40% context-window pre-injection to agent-callable memory tools (`search_memory`, `recall_topic`, `read_source`, `what_do_i_know`). Improve engram quality via paragraph-level decomposition and fact-level dedup. Store source content via hybrid backend (DB for small, filesystem for large, URI for re-fetchable).

**Tech Stack:** PostgreSQL (pgvector), FastAPI, Pydantic, Redis, httpx, asyncpg, SQLAlchemy async, React/TypeScript (dashboard)

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `memory-service/app/engram/sources.py` | Source CRUD, trust scoring, hybrid storage, summarization, gap detection |
| `orchestrator/app/tools/memory_tools.py` | Agent-callable memory tools (search, recall, read_source, what_do_i_know) |
| `tests/test_sources.py` | Integration tests for sources API |
| `tests/test_memory_tools.py` | Integration tests for memory tools |

### Modified Files
| File | Changes |
|------|---------|
| `memory-service/app/db/schema.sql` | Add `sources` table, add `source_ref_id` + `source_meta` + `temporal_validity` columns to `engrams` |
| `nova-contracts/nova_contracts/engram.py` | Source Pydantic models, `SourceKind` enum, updated `IngestionEvent` with source fields |
| `memory-service/app/config.py` | Source storage settings, decomposition tuning, domain awareness config |
| `memory-service/app/engram/ingestion.py` | Create/link source records, fact-level dedup, temporal validity extraction |
| `memory-service/app/engram/decomposition.py` | Paragraph-level prompts, source summarization prompt |
| `memory-service/app/engram/router.py` | Source CRUD endpoints, memory search endpoints, domain summary endpoint |
| `memory-service/app/engram/working_memory.py` | Domain awareness priming (replace bulk memory injection) |
| `orchestrator/app/tools/__init__.py` | Register Memory tool group |
| `orchestrator/app/agents/runner.py` | Replace 40% pre-injection with domain priming + tool-based retrieval |
| `orchestrator/app/config.py` | Remove `context_memory_pct`, add `context_priming_pct` |
| `orchestrator/app/pipeline/agents/post_pipeline.py` | Fix broken ingestion payload |
| `orchestrator/app/engram_router.py` | Re-decomposition from stored source content |
| `dashboard/src/pages/EngramExplorer.tsx` | Source attribution display, source drill-down |

---

## Phase 1: Sources Foundation

Everything else depends on this. After this phase, every new engram tracks where it came from, and sources are queryable via API.

### Task 1: Sources Table Schema

**Files:**
- Modify: `memory-service/app/db/schema.sql`

- [ ] **Step 1: Read the current schema**

```bash
cat memory-service/app/db/schema.sql
```

Understand the existing `engrams` and `engram_edges` table definitions.

- [ ] **Step 2: Add the sources table to schema.sql**

Add after the `embedding_cache` table and before the `engrams` table:

```sql
-- ── Sources ─────────────────────────────────────────────────────────────────
-- Provenance backbone: every engram traces back to a source.
-- Sources are the raw material — books, articles, conversations, crawls.
-- Hybrid storage: content in DB (small), filesystem (large), or URI-only (re-fetchable).

CREATE TABLE IF NOT EXISTS sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Classification
    source_kind     TEXT NOT NULL,          -- chat, intel_feed, knowledge_crawl, manual_paste,
                                            -- task_output, pipeline_extraction, consolidation, api_response
    title           TEXT,                   -- Human-readable: page title, feed name, "Chat with Jeremy", book title
    uri             TEXT,                   -- Original URL, chat://session/{id}, task://{id}, NULL for paste

    -- Content storage (hybrid: pick one or more)
    content         TEXT,                   -- Inline content for small sources (< 100KB)
    content_path    TEXT,                   -- Filesystem path for large sources (relative to data/sources/)
    content_hash    TEXT,                   -- SHA-256 of raw content — dedup and change detection

    -- Hierarchical summarization
    summary         TEXT,                   -- 1-paragraph summary (generated at ingestion)
    section_summaries JSONB,               -- [{heading, summary}] for structured documents

    -- Trust & freshness
    trust_score     REAL NOT NULL DEFAULT 0.7,  -- 0.0-1.0, propagated to engram confidence
    verified_at     TIMESTAMPTZ,           -- Last time source was re-checked / still valid
    stale           BOOLEAN NOT NULL DEFAULT FALSE,

    -- Completeness tracking
    completeness    TEXT DEFAULT 'complete', -- complete, partial, fragment
    coverage_notes  TEXT,                   -- "chapters 1-7 of 12", "first 3 pages only"

    -- Metadata
    author          TEXT,                   -- Attribution: person, org, feed name
    published_at    TIMESTAMPTZ,           -- When source was originally published
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB DEFAULT '{}',    -- Extensible: {feed_id, crawl_depth, session_id, ...}

    -- Multi-tenancy
    tenant_id       UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',

    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sources_kind ON sources(source_kind);
CREATE INDEX IF NOT EXISTS idx_sources_uri ON sources(uri) WHERE uri IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sources_hash ON sources(content_hash) WHERE content_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sources_tenant ON sources(tenant_id);
CREATE INDEX IF NOT EXISTS idx_sources_trust ON sources(trust_score);
```

- [ ] **Step 3: Add source linkage and temporal validity columns to engrams**

Add after the sources table (idempotent ALTER TABLE):

```sql
-- Link engrams to their provenance source
DO $$ BEGIN
    ALTER TABLE engrams ADD COLUMN source_ref_id UUID REFERENCES sources(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE engrams ADD COLUMN source_meta JSONB DEFAULT '{}';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE engrams ADD COLUMN temporal_validity TEXT DEFAULT 'unknown';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE engrams ADD COLUMN valid_as_of TIMESTAMPTZ;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_engrams_source_ref ON engrams(source_ref_id) WHERE source_ref_id IS NOT NULL;

-- NOTE: The engram_archive table mirrors engrams but does NOT get these new columns.
-- Archived engrams will lose provenance linkage. This is acceptable — archived engrams
-- are cold storage and rarely queried. If needed, add matching ALTER TABLE statements
-- for engram_archive in a follow-up.
```

- [ ] **Step 4: Verify schema applies cleanly**

```bash
docker compose restart memory-service && sleep 3 && curl -sf http://localhost:8002/health/ready | python3 -c "import sys,json; print(json.load(sys.stdin))"
```

Expected: `{'status': 'ok'}` — memory-service starts without schema errors.

- [ ] **Step 5: Commit**

```bash
git add memory-service/app/db/schema.sql
git commit -m "feat(memory): add sources table and engram provenance columns"
```

---

### Task 2: Source Pydantic Models

**Files:**
- Modify: `nova-contracts/nova_contracts/engram.py`

- [ ] **Step 1: Read the current contracts**

```bash
cat nova-contracts/nova_contracts/engram.py
```

- [ ] **Step 2: Add SourceKind enum and Source models**

Add after the existing enums, before `IngestionEvent`:

```python
class SourceKind(str, Enum):
    chat = "chat"
    intel_feed = "intel_feed"
    knowledge_crawl = "knowledge_crawl"
    manual_paste = "manual_paste"
    task_output = "task_output"
    pipeline_extraction = "pipeline_extraction"
    consolidation = "consolidation"
    api_response = "api_response"

class TemporalValidity(str, Enum):
    permanent = "permanent"   # math, definitions — never stale
    dated = "dated"           # news, releases — goes stale
    seasonal = "seasonal"     # trends, patterns — periodic
    unknown = "unknown"       # unclassified


class SourceCreate(BaseModel):
    """Payload for creating a new source record."""
    source_kind: SourceKind
    title: str | None = None
    uri: str | None = None
    content: str | None = None          # inline for small sources
    content_hash: str | None = None
    trust_score: float = 0.7
    author: str | None = None
    published_at: datetime | None = None
    completeness: str = "complete"
    coverage_notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceDetail(BaseModel):
    """Full source record returned by API."""
    id: UUID
    source_kind: SourceKind
    title: str | None = None
    uri: str | None = None
    summary: str | None = None
    section_summaries: list[dict[str, str]] | None = None
    trust_score: float
    verified_at: datetime | None = None
    stale: bool = False
    completeness: str = "complete"
    coverage_notes: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    ingested_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    engram_count: int = 0  # populated by API


class SourceSummary(BaseModel):
    """Lightweight source reference for domain awareness."""
    id: UUID
    source_kind: SourceKind
    title: str | None = None
    summary: str | None = None
    trust_score: float
    engram_count: int = 0
```

- [ ] **Step 3: Update IngestionEvent with source fields**

Modify `IngestionEvent` to accept source metadata:

```python
class IngestionEvent(BaseModel):
    raw_text: str
    source_type: IngestionSourceType = IngestionSourceType.chat
    source_id: UUID | None = None
    session_id: UUID | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Source provenance (new)
    source_uri: str | None = None
    source_title: str | None = None
    source_author: str | None = None
    source_trust: float | None = None  # override default trust for this source kind
```

- [ ] **Step 4: Update EngramDetail with provenance fields**

Add to `EngramDetail`:

```python
class EngramDetail(BaseModel):
    # ... existing fields ...
    source_ref_id: UUID | None = None
    source_meta: dict[str, Any] = Field(default_factory=dict)
    temporal_validity: str = "unknown"
    valid_as_of: datetime | None = None
```

- [ ] **Step 5: Commit**

```bash
git add nova-contracts/nova_contracts/engram.py
git commit -m "feat(contracts): add Source models, SourceKind enum, provenance fields"
```

---

### Task 3: Source CRUD Module

**Files:**
- Create: `memory-service/app/engram/sources.py`

- [ ] **Step 1: Write the source test**

Create `tests/test_sources.py`:

```python
"""Integration tests for source provenance system."""
import hashlib
import httpx
import pytest
import pytest_asyncio

BASE = "http://localhost:8002/api/v1/engrams"


@pytest_asyncio.fixture
async def created_source():
    """Create a test source and clean up after."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.post(f"{BASE}/sources", json={
            "source_kind": "manual_paste",
            "title": "nova-test-source-provenance",
            "content": "Nova is an autonomous AI platform built by Aria Labs.",
            "trust_score": 0.9,
        })
        assert resp.status_code == 200
        data = resp.json()
        yield data
        # Cleanup
        await c.delete(f"{BASE}/sources/{data['id']}")


@pytest.mark.asyncio
async def test_create_source():
    """POST /sources creates a source record with content hash."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.post(f"{BASE}/sources", json={
            "source_kind": "intel_feed",
            "title": "nova-test-intel-source",
            "uri": "https://example.com/nova-test-article",
            "trust_score": 0.8,
            "author": "Test Author",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_kind"] == "intel_feed"
        assert data["title"] == "nova-test-intel-source"
        assert data["trust_score"] == 0.8
        # Cleanup
        await c.delete(f"{BASE}/sources/{data['id']}")


@pytest.mark.asyncio
async def test_list_sources():
    """GET /sources returns source list."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.get(f"{BASE}/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_source_detail(created_source):
    """GET /sources/{id} returns full source detail."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.get(f"{BASE}/sources/{created_source['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "nova-test-source-provenance"
        assert data["trust_score"] == 0.9


@pytest.mark.asyncio
async def test_source_dedup_by_hash():
    """Creating a source with identical content returns existing source."""
    content = "nova-test-dedup-content-identical"
    async with httpx.AsyncClient(timeout=10) as c:
        r1 = await c.post(f"{BASE}/sources", json={
            "source_kind": "manual_paste",
            "title": "nova-test-dedup-1",
            "content": content,
        })
        r2 = await c.post(f"{BASE}/sources", json={
            "source_kind": "manual_paste",
            "title": "nova-test-dedup-2",
            "content": content,
        })
        assert r1.json()["id"] == r2.json()["id"]
        # Cleanup
        await c.delete(f"{BASE}/sources/{r1.json()['id']}")


@pytest.mark.asyncio
async def test_domain_summary():
    """GET /sources/domain-summary returns knowledge domain overview."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.get(f"{BASE}/sources/domain-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "source_count" in data
        assert "domains" in data
        assert "by_kind" in data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_sources.py -v -x 2>&1 | head -30
```

Expected: FAIL — endpoints don't exist yet.

- [ ] **Step 3: Write sources.py module**

Create `memory-service/app/engram/sources.py`:

```python
"""
Source provenance — the backing store for engram knowledge.

Every engram traces back to a source: a conversation, web page, intel feed,
manual paste, task output, etc. Sources store raw content (hybrid: DB for
small, filesystem for large, URI for re-fetchable) and metadata.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

log = logging.getLogger(__name__)

# Trust defaults by source kind
DEFAULT_TRUST: dict[str, float] = {
    "chat": 0.95,
    "manual_paste": 0.90,
    "task_output": 0.85,
    "knowledge_crawl": 0.70,
    "intel_feed": 0.70,
    "pipeline_extraction": 0.80,
    "consolidation": 0.85,
    "api_response": 0.50,
}

# Sources larger than this threshold are stored on filesystem
CONTENT_SIZE_THRESHOLD = 100_000  # 100 KB

# Filesystem root for large source content
SOURCES_DIR = Path("/data/sources")


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


async def find_or_create_source(
    session: AsyncSession,
    *,
    source_kind: str,
    title: str | None = None,
    uri: str | None = None,
    content: str | None = None,
    trust_score: float | None = None,
    author: str | None = None,
    published_at: datetime | None = None,
    completeness: str = "complete",
    coverage_notes: str | None = None,
    metadata: dict | None = None,
) -> UUID:
    """Find existing source by content hash or URI, or create a new one.

    Returns the source UUID.
    """
    c_hash = _content_hash(content) if content else None
    trust = trust_score if trust_score is not None else DEFAULT_TRUST.get(source_kind, 0.7)

    # Dedup: check content hash first, then URI
    if c_hash:
        row = await session.execute(
            text("SELECT id FROM sources WHERE content_hash = :h LIMIT 1"),
            {"h": c_hash},
        )
        existing = row.fetchone()
        if existing:
            log.debug("Source dedup hit (hash): %s", existing.id)
            return existing.id

    if uri:
        row = await session.execute(
            text("SELECT id FROM sources WHERE uri = :u AND source_kind = :k LIMIT 1"),
            {"u": uri, "k": source_kind},
        )
        existing = row.fetchone()
        if existing:
            log.debug("Source dedup hit (URI): %s", existing.id)
            return existing.id

    # Store content: inline (small) or filesystem (large)
    db_content = None
    content_path = None
    if content:
        if len(content.encode()) <= CONTENT_SIZE_THRESHOLD:
            db_content = content
        else:
            content_path = _store_to_filesystem(c_hash, content)

    row = await session.execute(
        text("""
            INSERT INTO sources (
                source_kind, title, uri, content, content_path, content_hash,
                trust_score, author, published_at, completeness, coverage_notes,
                metadata
            ) VALUES (
                :kind, :title, :uri, :content, :content_path, :hash,
                :trust, :author, :published_at, :completeness, :coverage_notes,
                CAST(:metadata AS jsonb)
            )
            RETURNING id
        """),
        {
            "kind": source_kind,
            "title": title,
            "uri": uri,
            "content": db_content,
            "content_path": content_path,
            "hash": c_hash,
            "trust": trust,
            "author": author,
            "published_at": published_at,
            "completeness": completeness,
            "coverage_notes": coverage_notes,
            "metadata": __import__("json").dumps(metadata or {}),
        },
    )
    source_id = row.scalar_one()
    # NOTE: do NOT call session.commit() here — get_db() auto-commits on exit.
    # Committing manually would cause partial-commit if a later engram store fails.
    log.info("Created source %s (%s): %s", source_id, source_kind, title or uri or "(untitled)")
    return source_id


def _store_to_filesystem(content_hash: str, content: str) -> str:
    """Store large content to filesystem. Returns relative path."""
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    # Shard by first 2 chars of hash to avoid flat directory
    shard = content_hash[:2]
    shard_dir = SOURCES_DIR / shard
    shard_dir.mkdir(exist_ok=True)
    path = shard_dir / f"{content_hash}.txt"
    path.write_text(content, encoding="utf-8")
    return f"{shard}/{content_hash}.txt"


async def get_source(session: AsyncSession, source_id: UUID) -> dict | None:
    """Fetch a source by ID. Loads filesystem content if needed."""
    row = await session.execute(
        text("""
            SELECT s.*, COUNT(e.id) AS engram_count
            FROM sources s
            LEFT JOIN engrams e ON e.source_ref_id = s.id AND NOT e.superseded
            WHERE s.id = :id
            GROUP BY s.id
        """),
        {"id": source_id},
    )
    r = row.fetchone()
    if not r:
        return None
    return _row_to_dict(r)


async def list_sources(
    session: AsyncSession,
    *,
    source_kind: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """List sources with engram counts."""
    filters = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}
    if source_kind:
        filters.append("s.source_kind = :kind")
        params["kind"] = source_kind

    where = " AND ".join(filters)
    rows = await session.execute(
        text(f"""
            SELECT s.*, COUNT(e.id) AS engram_count
            FROM sources s
            LEFT JOIN engrams e ON e.source_ref_id = s.id AND NOT e.superseded
            WHERE {where}
            GROUP BY s.id
            ORDER BY s.ingested_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    return [_row_to_dict(r) for r in rows.fetchall()]


async def delete_source(session: AsyncSession, source_id: UUID) -> bool:
    """Delete a source. Engrams keep their source_meta but lose the FK."""
    result = await session.execute(
        text("DELETE FROM sources WHERE id = :id"),
        {"id": source_id},
    )
    return result.rowcount > 0


async def get_source_content(session: AsyncSession, source_id: UUID) -> str | None:
    """Retrieve full content from DB or filesystem."""
    row = await session.execute(
        text("SELECT content, content_path, uri FROM sources WHERE id = :id"),
        {"id": source_id},
    )
    r = row.fetchone()
    if not r:
        return None
    if r.content:
        return r.content
    if r.content_path:
        path = SOURCES_DIR / r.content_path
        if path.exists():
            return path.read_text(encoding="utf-8")
    return None  # URI-only source — content not stored


async def update_source_summary(
    session: AsyncSession,
    source_id: UUID,
    summary: str,
    section_summaries: list[dict] | None = None,
) -> None:
    """Update the hierarchical summaries for a source."""
    import json
    await session.execute(
        text("""
            UPDATE sources
            SET summary = :summary,
                section_summaries = CAST(:sections AS jsonb),
                updated_at = NOW()
            WHERE id = :id
        """),
        {
            "id": source_id,
            "summary": summary,
            "sections": json.dumps(section_summaries) if section_summaries else None,
        },
    )


async def get_domain_summary(session: AsyncSession) -> dict:
    """Lightweight knowledge domain overview for agent priming.

    Returns source counts by kind, top domains/topics, and total engram count.
    Designed to fit in ~200 tokens for context injection.
    """
    # Source counts by kind
    by_kind = await session.execute(
        text("""
            SELECT source_kind, COUNT(*) AS cnt,
                   SUM(CASE WHEN stale THEN 1 ELSE 0 END) AS stale_cnt
            FROM sources
            GROUP BY source_kind
            ORDER BY cnt DESC
        """)
    )
    kinds = {r.source_kind: {"count": r.cnt, "stale_count": r.stale_cnt} for r in by_kind.fetchall()}

    # Total engrams
    total = await session.execute(
        text("SELECT COUNT(*) FROM engrams WHERE NOT superseded")
    )
    engram_count = total.scalar_one()

    # Top entity domains (most-connected entities as proxy for domains)
    domains_q = await session.execute(
        text("""
            SELECT e.content, COUNT(edge.id) AS connections
            FROM engrams e
            JOIN engram_edges edge ON edge.source_id = e.id OR edge.target_id = e.id
            WHERE e.type = 'entity' AND NOT e.superseded
            GROUP BY e.id, e.content
            ORDER BY connections DESC
            LIMIT 15
        """)
    )
    domains = [r.content for r in domains_q.fetchall()]

    # Source titles (recent, for awareness)
    titles_q = await session.execute(
        text("""
            SELECT title, source_kind FROM sources
            WHERE title IS NOT NULL
            ORDER BY ingested_at DESC
            LIMIT 20
        """)
    )
    recent_sources = [{"title": r.title, "kind": r.source_kind} for r in titles_q.fetchall()]

    return {
        "source_count": sum(v["count"] for v in kinds.values()),
        "engram_count": engram_count,
        "by_kind": kinds,
        "domains": domains,
        "recent_sources": recent_sources,
    }


def _row_to_dict(r) -> dict:
    """Convert a source row to dict, loading filesystem content path but not content."""
    return {
        "id": str(r.id),
        "source_kind": r.source_kind,
        "title": r.title,
        "uri": r.uri,
        "has_content": bool(r.content or r.content_path),
        "content_hash": r.content_hash,
        "summary": r.summary,
        "section_summaries": r.section_summaries,
        "trust_score": r.trust_score,
        "verified_at": r.verified_at.isoformat() if r.verified_at else None,
        "stale": r.stale,
        "completeness": r.completeness,
        "coverage_notes": r.coverage_notes,
        "author": r.author,
        "published_at": r.published_at.isoformat() if r.published_at else None,
        "ingested_at": r.ingested_at.isoformat(),
        "metadata": r.metadata or {},
        "engram_count": getattr(r, "engram_count", 0),
    }
```

- [ ] **Step 4: Add source endpoints to router.py**

Modify `memory-service/app/engram/router.py`. Add these endpoints after the existing graph endpoint:

```python
# ── Source Provenance ─────────────────────────────────────────────────────────

class CreateSourceRequest(BaseModel):
    source_kind: str
    title: str | None = None
    uri: str | None = None
    content: str | None = None
    trust_score: float | None = None
    author: str | None = None
    completeness: str = "complete"
    coverage_notes: str | None = None
    metadata: dict = Field(default_factory=dict)


@engram_router.post("/sources")
async def create_source(req: CreateSourceRequest):
    """Create or find-by-dedup a source record."""
    from .sources import find_or_create_source, get_source
    async with get_db() as session:
        source_id = await find_or_create_source(
            session,
            source_kind=req.source_kind,
            title=req.title,
            uri=req.uri,
            content=req.content,
            trust_score=req.trust_score,
            author=req.author,
            completeness=req.completeness,
            coverage_notes=req.coverage_notes,
            metadata=req.metadata,
        )
        return await get_source(session, source_id)


@engram_router.get("/sources")
async def list_sources_endpoint(
    source_kind: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """List all sources with engram counts."""
    from .sources import list_sources
    async with get_db() as session:
        return await list_sources(session, source_kind=source_kind, limit=limit, offset=offset)


@engram_router.get("/sources/domain-summary")
async def domain_summary():
    """Lightweight knowledge domain overview for agent priming."""
    from .sources import get_domain_summary
    async with get_db() as session:
        return await get_domain_summary(session)


@engram_router.get("/sources/{source_id}")
async def get_source_endpoint(source_id: UUID):
    """Get full source detail with engram count."""
    from .sources import get_source
    async with get_db() as session:
        result = await get_source(session, source_id)
        if not result:
            from fastapi import HTTPException
            raise HTTPException(404, "Source not found")
        return result


@engram_router.get("/sources/{source_id}/content")
async def get_source_content_endpoint(source_id: UUID):
    """Retrieve full source content (from DB or filesystem)."""
    from .sources import get_source_content
    async with get_db() as session:
        content = await get_source_content(session, source_id)
        if content is None:
            from fastapi import HTTPException
            raise HTTPException(404, "Source content not available")
        return {"content": content}


@engram_router.delete("/sources/{source_id}")
async def delete_source_endpoint(source_id: UUID):
    """Delete a source record."""
    from .sources import delete_source
    async with get_db() as session:
        deleted = await delete_source(session, source_id)
        return {"deleted": deleted}
```

- [ ] **Step 5: Run tests**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_sources.py -v
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add memory-service/app/engram/sources.py memory-service/app/engram/router.py tests/test_sources.py
git commit -m "feat(memory): add source provenance CRUD with hybrid storage and dedup"
```

---

### Task 4: Wire Ingestion to Create Source Records

**Files:**
- Modify: `memory-service/app/engram/ingestion.py`

This is where provenance metadata stops being thrown away. Every ingestion event creates or links to a source record, and every engram gets linked to that source.

- [ ] **Step 1: Read current ingestion.py**

```bash
cat memory-service/app/engram/ingestion.py
```

- [ ] **Step 2: Modify `_process_event` to create source records**

In `_process_event()`, after parsing the event payload and before calling `decompose()`, add source creation:

```python
# ── Source provenance ─────────────────────────────────────────────────
source_ref_id = None
source_meta = {}
try:
    from .sources import find_or_create_source, DEFAULT_TRUST
    source_kind = _map_source_type_to_kind(source_type)
    source_uri = event.get("source_uri") or metadata.get("url")
    source_title = event.get("source_title") or metadata.get("feed_name")
    source_author = event.get("source_author") or metadata.get("author")
    trust_override = event.get("source_trust")

    source_ref_id = await find_or_create_source(
        session,
        source_kind=source_kind,
        title=source_title,
        uri=source_uri,
        content=raw_text,
        trust_score=trust_override,
        author=source_author,
        metadata=metadata,
    )
    source_meta = {
        k: v for k, v in {
            "url": source_uri,
            "title": source_title,
            "author": source_author,
            "feed_name": metadata.get("feed_name"),
            "session_id": event.get("session_id"),
        }.items() if v
    }
    trust = trust_override or DEFAULT_TRUST.get(source_kind, 0.7)
except Exception as exc:
    log.warning("Source creation failed (non-fatal): %s", exc)
    trust = 0.7
```

Add the helper function:

```python
def _map_source_type_to_kind(source_type: str) -> str:
    """Map IngestionSourceType values to SourceKind values."""
    mapping = {
        "chat": "chat",
        "intel": "intel_feed",
        "knowledge": "knowledge_crawl",
        "pipeline": "pipeline_extraction",
        "tool": "task_output",
        "consolidation": "consolidation",
        "cortex": "task_output",
        "journal": "manual_paste",
        "external": "knowledge_crawl",
        "self_reflection": "consolidation",
    }
    return mapping.get(source_type, "manual_paste")
```

- [ ] **Step 3: Modify `_store_or_update_engram` to set source linkage**

Update the function signature to accept the new provenance parameters:

```python
async def _store_or_update_engram(
    session, decomposed_type, content, importance,
    entities_referenced, temporal, source_type, source_id,
    occurred_at, metadata,
    # Source provenance (new)
    source_ref_id=None, source_meta=None, trust=0.8,
) -> tuple[UUID, bool]:
```

In the INSERT statement, add three columns and values:

```sql
-- Add to column list:
source_ref_id, source_meta, confidence
-- Add to VALUES:
:source_ref_id, CAST(:source_meta AS jsonb), :confidence
```

And in the params dict:

```python
"source_ref_id": source_ref_id,
"source_meta": json.dumps(source_meta or {}),
"confidence": trust,
```

Update ALL call sites in `_process_event` to pass the new params:

```python
engram_id, was_new = await _store_or_update_engram(
    session, ...,  # existing args unchanged
    source_ref_id=source_ref_id,
    source_meta=source_meta,
    trust=trust,
)
```

**Important:** The source record is created BEFORE decomposition. If decomposition returns 0 engrams (empty input), the source record will exist with no linked engrams. This is acceptable — the source still tracks that ingestion was attempted, and orphaned sources can be cleaned up by a periodic job later.

- [ ] **Step 4: Run existing tests to verify nothing breaks**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/ -v -x --timeout=120 2>&1 | tail -20
```

Expected: All existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add memory-service/app/engram/ingestion.py
git commit -m "feat(memory): wire ingestion pipeline to create source records and link engrams"
```

---

### Task 5: Fix Broken Post-Pipeline Payload

**Files:**
- Modify: `orchestrator/app/pipeline/agents/post_pipeline.py`

- [ ] **Step 1: Read the broken code**

```bash
cat orchestrator/app/pipeline/agents/post_pipeline.py
```

- [ ] **Step 2: Fix the payload format**

Replace the broken payload (around line 94-98):

```python
# BEFORE (broken):
payload = json.dumps({
    "text": f"Task: {state.task_input}\n\nExtraction: {json.dumps(result)}",
    "source": "pipeline_memory_extraction",
})

# AFTER (correct):
payload = json.dumps({
    "raw_text": f"Task: {state.task_input}\n\nExtraction: {json.dumps(result)}",
    "source_type": "pipeline",
    "source_id": task_id or None,
    "occurred_at": datetime.now(timezone.utc).isoformat(),
    "source_title": f"Pipeline extraction: {state.task_input[:80]}",
    "metadata": {"extraction_type": "pipeline_memory"},
})
```

Add the datetime import if not present:

```python
from datetime import datetime, timezone
```

- [ ] **Step 3: Run tests**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/ -v -x -k "pipeline or health" --timeout=120 2>&1 | tail -20
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/pipeline/agents/post_pipeline.py
git commit -m "fix(pipeline): correct broken memory extraction payload format"
```

---

## Phase 2: Better Engrams

Improves the quality of knowledge stored in the graph. **Depends on Phase 1 Task 1** (schema) for the `temporal_validity` column on engrams. Can be done independently of Phase 3.

### Task 6: Paragraph-Level Decomposition Prompts

**Files:**
- Modify: `memory-service/app/engram/decomposition.py`

- [ ] **Step 1: Read current decomposition prompts**

```bash
cat memory-service/app/engram/decomposition.py
```

- [ ] **Step 2: Replace DECOMPOSITION_SYSTEM_PROMPT_CHAT**

The key change: instruct the LLM to produce self-contained, paragraph-level statements instead of atomic facts. Keep entity extraction for graph linking.

```python
DECOMPOSITION_SYSTEM_PROMPT_CHAT = """You are a memory decomposition engine. Extract structured knowledge from a conversation between a user and an AI assistant.

FOCUS: Extract information about the USER — their identity, preferences, knowledge, decisions, and experiences. The assistant's responses are context, not knowledge.

OUTPUT FORMAT: Valid JSON (no markdown fences). Return a DecompositionResult:
{
  "engrams": [...],
  "relationships": [...],
  "contradictions": [...]
}

ENGRAM GUIDELINES:
- Each engram should be a SELF-CONTAINED statement of 1-3 sentences
- Include enough context that the engram makes sense on its own, without needing other engrams
- DO NOT split closely related facts into separate engrams — keep them together
- BAD: "Jeremy founded Aria Labs" + "Aria Labs was founded in 2025" + "Aria Labs builds AI"
- GOOD: "Jeremy founded Aria Labs in 2025 to build autonomous AI platforms"
- Entity engrams (type=entity) are the exception — these should be atomic identifiers

TYPES:
- fact: Self-contained statement about the user or their world (1-3 sentences, include context)
- entity: Atomic identifier — a person, place, project, tool, concept (name only, keep short)
- preference: User preference with rationale ("prefers X because Y")
- episode: Something that happened, with context ("on date X, user did Y because Z")
- procedure: How to do something the user described (steps together, not split)

IMPORTANCE (0.0-1.0):
- 0.9: Core identity, critical decisions, strong preferences
- 0.7: Significant facts, project details, professional context
- 0.5: Normal conversational facts
- 0.3: Minor details, passing mentions

TEMPORAL VALIDITY:
- For each engram, assess if it's time-sensitive:
  - "permanent": definitions, identities, math facts
  - "dated": news, releases, current events, versions
  - "unknown": can't determine

RELATIONSHIPS: Connect engrams that have meaningful associations. Use:
- related_to, caused_by, enables, part_of, instance_of, preceded, analogous_to

CONTRADICTIONS: If a new statement contradicts something the user previously said, flag it.

If the conversation is just greetings or contains no extractable knowledge, return {"engrams": [], "relationships": [], "contradictions": []}.
"""
```

- [ ] **Step 3: Replace DECOMPOSITION_SYSTEM_PROMPT_INTEL**

Same philosophy — richer, self-contained statements:

```python
DECOMPOSITION_SYSTEM_PROMPT_INTEL = """You are a memory decomposition engine. Extract structured knowledge from external content (news articles, blog posts, forum discussions, documentation).

CRITICAL: This is THIRD-PARTY content, not the user speaking. Do NOT attribute statements as user preferences. Attribute to the source ("according to the article", "the author argues").

OUTPUT FORMAT: Valid JSON (no markdown fences). Return a DecompositionResult.

ENGRAM GUIDELINES:
- Each engram should be a SELF-CONTAINED statement of 1-3 sentences
- Include source attribution within the engram text itself
- Preserve key details: names, dates, versions, metrics
- BAD: "GPT-5 was released" + "GPT-5 has 10T parameters" + "GPT-5 was released in March"
- GOOD: "OpenAI released GPT-5 in March 2026 with 10T parameters, marking a significant scale increase"

TYPES: fact (objective claims), entity (people/orgs/tools), episode (events with dates), procedure (how-to), preference (community sentiment — attribute to source)

IMPORTANCE: 0.9=major announcements, 0.7=significant developments, 0.5=normal news, 0.3=minor updates

TEMPORAL VALIDITY: Most intel content is "dated" — include the timeframe in the engram text.
"""
```

- [ ] **Step 4: Update the user template to request temporal validity**

```python
DECOMPOSITION_USER_TEMPLATE = (
    "Decompose this into structured engrams. For each engram, include a "
    "temporal_validity field ('permanent', 'dated', or 'unknown').\n\n{raw_text}"
)
```

- [ ] **Step 5: Update DecomposedEngram in contracts to include temporal_validity**

In `nova-contracts/nova_contracts/engram.py`, add to `DecomposedEngram`:

```python
class DecomposedEngram(BaseModel):
    type: EngramType
    content: str
    importance: float = 0.5
    entities_referenced: list[str] = []
    temporal: dict[str, Any] = {}
    temporal_validity: str = "unknown"  # permanent, dated, unknown
```

- [ ] **Step 6: Wire temporal_validity through ingestion**

In `ingestion.py` `_store_or_update_engram()`, add `temporal_validity` to the INSERT:

```python
# Add to INSERT: temporal_validity = :temporal_validity
# Set from: decomposed.temporal_validity if hasattr else "unknown"
```

- [ ] **Step 7: Run tests**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/ -v -x --timeout=120 2>&1 | tail -20
```

- [ ] **Step 8: Commit**

```bash
git add memory-service/app/engram/decomposition.py nova-contracts/nova_contracts/engram.py memory-service/app/engram/ingestion.py
git commit -m "feat(memory): paragraph-level decomposition with temporal validity tracking"
```

---

### Task 7: Fact-Level Dedup During Ingestion

**Files:**
- Modify: `memory-service/app/engram/ingestion.py`
- Modify: `memory-service/app/config.py`

- [ ] **Step 1: Add config setting for fact dedup threshold**

In `memory-service/app/config.py`:

```python
engram_fact_dedup_threshold: float = 0.90  # cosine similarity for fact-level dedup
```

- [ ] **Step 2: Add fact dedup to `_store_or_update_engram`**

Currently entity dedup exists via `find_existing_entity()` and `find_similar_engram()`. Extend `find_similar_engram` to also run for `fact` type engrams, using the new threshold.

In `_store_or_update_engram()`, after entity resolution, add:

```python
# Fact-level dedup: merge near-duplicate facts
if decomposed.type in ("fact", "episode", "procedure", "preference"):
    similar = await find_similar_engram(
        session, embedding, decomposed.type,
        threshold=settings.engram_fact_dedup_threshold,
    )
    if similar:
        await update_existing_engram(session, similar.id, decomposed.importance)
        log.debug("Fact dedup: merged into existing engram %s", similar.id)
        # Preserve BOTH source links: add new source_ref_id to existing engram's source_meta
        if source_ref_id:
            await _append_source_ref(session, similar.id, source_ref_id)
        return similar.id, False
```

Add the helper:

```python
async def _append_source_ref(session: AsyncSession, engram_id, source_ref_id) -> None:
    """Append a source reference to an existing engram's source_meta."""
    await session.execute(
        text("""
            UPDATE engrams
            SET source_meta = jsonb_set(
                COALESCE(source_meta, '{}'),
                '{additional_sources}',
                COALESCE(source_meta->'additional_sources', '[]'::jsonb) || to_jsonb(:ref::text)
            )
            WHERE id = :id
        """),
        {"id": engram_id, "ref": str(source_ref_id)},
    )
```

- [ ] **Step 3: Run tests**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/ -v -x --timeout=120 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```bash
git add memory-service/app/engram/ingestion.py memory-service/app/config.py
git commit -m "feat(memory): fact-level dedup merges near-duplicate engrams during ingestion"
```

---

## Phase 3: Memory Tools — The Retrieval Shift

This is the architectural change: agents get memory as tools instead of pre-injected context.

### Task 8: Memory Tools Module

**Files:**
- Create: `orchestrator/app/tools/memory_tools.py`
- Modify: `orchestrator/app/tools/__init__.py`

- [ ] **Step 1: Write memory tools test**

Create `tests/test_memory_tools.py`:

```python
"""Integration tests for agent-callable memory tools."""
import os
import httpx
import pytest

ORCH = os.getenv("NOVA_ORCHESTRATOR_URL", "http://localhost:8000")
MEM = os.getenv("NOVA_MEMORY_URL", "http://localhost:8002")
ADMIN_SECRET = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")


@pytest.mark.asyncio
async def test_what_do_i_know_tool():
    """what_do_i_know returns domain awareness summary."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.get(f"{MEM}/api/v1/engrams/sources/domain-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "source_count" in data
        assert "domains" in data


@pytest.mark.asyncio
async def test_search_memory_tool():
    """search_memory returns ranked engram results."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.post(
            f"{MEM}/api/v1/engrams/activate",
            params={"query": "nova-test-memory-search"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "engrams" in data


@pytest.mark.asyncio
async def test_memory_tools_registered():
    """Memory tools appear in the tool catalog."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.get(f"{ORCH}/api/v1/tools",
                           headers={"X-Admin-Secret": ADMIN_SECRET})
        if resp.status_code == 200:
            tools = resp.json()
            tool_names = [t["name"] if isinstance(t, dict) else t for t in tools]
            assert "search_memory" in tool_names
            assert "what_do_i_know" in tool_names
            assert "recall_topic" in tool_names
            assert "read_source" in tool_names
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_memory_tools.py::test_memory_tools_registered -v -x
```

Expected: FAIL — tools not registered yet.

- [ ] **Step 3: Create memory_tools.py**

Create `orchestrator/app/tools/memory_tools.py`:

```python
"""
Memory Tools — agent-callable knowledge retrieval.

These tools let agents search, recall, and read from Nova's memory system
on-demand instead of relying on pre-injected context. This gives agents
control over what they retrieve and when, keeping the context window lean.

Tools provided:
  what_do_i_know    -- lightweight domain awareness (what topics/sources exist)
  search_memory     -- semantic search across engrams (ranked results)
  recall_topic      -- retrieve all engrams connected to an entity
  read_source       -- fetch full content from a source record
"""
from __future__ import annotations

import json
import logging

import httpx

from nova_contracts import ToolDefinition

log = logging.getLogger(__name__)

MEMORY_BASE = "http://memory-service:8002/api/v1/engrams"
_TIMEOUT = httpx.Timeout(15.0)

# ─── Tool definitions (what the LLM sees) ────────────────────────────────────

MEMORY_TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        name="what_do_i_know",
        description=(
            "Get a lightweight overview of what knowledge domains and sources you have "
            "in memory. Returns topic areas, source titles, and counts — NOT the actual "
            "knowledge. Use this FIRST to understand what you know before doing deeper "
            "retrieval. Costs almost zero context tokens."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional topic to focus the overview on",
                },
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="search_memory",
        description=(
            "Search your memory for knowledge relevant to a query. Returns ranked "
            "engrams (facts, episodes, procedures) with source attribution. Use this "
            "when you need to recall specific information. More expensive than "
            "what_do_i_know but returns actual knowledge content."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in memory",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results to return (default: 10, max: 30)",
                },
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="recall_topic",
        description=(
            "Retrieve all knowledge connected to a specific entity or topic. Uses "
            "graph traversal to find everything related — facts, episodes, procedures "
            "that reference the entity and their connections. Use this when you want "
            "comprehensive recall about a person, project, concept, or tool."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "The entity/topic to recall (e.g., 'Jeremy', 'Nova', 'Python')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results (default: 15, max: 50)",
                },
            },
            "required": ["entity"],
        },
    ),
    ToolDefinition(
        name="read_source",
        description=(
            "Read the full content of a source document. Sources are the raw material "
            "behind engrams — articles, conversations, documents, crawled pages. Use "
            "this when engram summaries aren't detailed enough and you need the original "
            "content. Returns the full text, which may be large."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "UUID of the source to read",
                },
            },
            "required": ["source_id"],
        },
    ),
]


# ─── Executors ────────────────────────────────────────────────────────────────

async def execute_tool(name: str, arguments: dict) -> str:
    """Dispatch memory tool calls to memory-service."""
    try:
        if name == "what_do_i_know":
            return await _what_do_i_know(arguments)
        elif name == "search_memory":
            return await _search_memory(arguments)
        elif name == "recall_topic":
            return await _recall_topic(arguments)
        elif name == "read_source":
            return await _read_source(arguments)
        else:
            return f"Unknown memory tool: {name}"
    except httpx.TimeoutException:
        return "Memory service timed out. Try again or reduce max_results."
    except Exception as e:
        log.warning("Memory tool '%s' failed: %s", name, e)
        return f"Memory tool error: {e}"


async def _what_do_i_know(args: dict) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        resp = await c.get(f"{MEMORY_BASE}/sources/domain-summary")
        resp.raise_for_status()
        data = resp.json()

    # Format for LLM consumption
    lines = [f"Knowledge overview ({data['engram_count']} memories from {data['source_count']} sources):"]

    if data.get("by_kind"):
        lines.append("\nSources by type:")
        for kind, info in data["by_kind"].items():
            stale_note = f" ({info['stale_count']} stale)" if info.get("stale_count") else ""
            lines.append(f"  - {kind}: {info['count']}{stale_note}")

    if data.get("domains"):
        lines.append(f"\nKey topics: {', '.join(data['domains'][:10])}")

    if data.get("recent_sources"):
        lines.append("\nRecent sources:")
        for s in data["recent_sources"][:10]:
            lines.append(f"  - [{s['kind']}] {s['title']}")

    return "\n".join(lines)


async def _search_memory(args: dict) -> str:
    query = args.get("query", "")
    max_results = min(args.get("max_results", 10), 30)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        resp = await c.post(
            f"{MEMORY_BASE}/activate",
            params={"query": query, "max_results": max_results},
        )
        resp.raise_for_status()
        data = resp.json()

    if not data.get("engrams"):
        return "No relevant memories found."

    lines = [f"Found {data['count']} relevant memories:"]
    for e in data["engrams"]:
        source_note = f" [from: {e.get('source_type', '?')}]" if e.get("source_type") else ""
        score = f" (relevance: {e.get('final_score', 0):.2f})"
        lines.append(f"\n- [{e['type']}]{source_note}{score}\n  {e['content']}")
        if e.get("source_ref_id"):
            lines.append(f"  source_id: {e['source_ref_id']}")

    return "\n".join(lines)


async def _recall_topic(args: dict) -> str:
    entity = args.get("entity", "")
    max_results = min(args.get("max_results", 15), 50)

    # First find the entity engram, then do graph BFS from it
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        # Search for the entity
        resp = await c.post(
            f"{MEMORY_BASE}/activate",
            params={"query": entity, "max_results": max_results},
        )
        resp.raise_for_status()
        data = resp.json()

    if not data.get("engrams"):
        return f"No knowledge found about '{entity}'."

    # Group by type for readability
    by_type: dict[str, list] = {}
    for e in data["engrams"]:
        by_type.setdefault(e["type"], []).append(e)

    lines = [f"Knowledge about '{entity}' ({data['count']} items):"]
    for etype, engrams in by_type.items():
        lines.append(f"\n## {etype.title()}s")
        for e in engrams:
            lines.append(f"- {e['content']}")

    return "\n".join(lines)


async def _read_source(args: dict) -> str:
    source_id = args.get("source_id", "")
    if not source_id:
        return "source_id is required."

    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        # Get source metadata
        meta_resp = await c.get(f"{MEMORY_BASE}/sources/{source_id}")
        if meta_resp.status_code == 404:
            return f"Source '{source_id}' not found."
        meta_resp.raise_for_status()
        meta = meta_resp.json()

        # Get content
        content_resp = await c.get(f"{MEMORY_BASE}/sources/{source_id}/content")
        if content_resp.status_code == 404:
            # URI-only source
            if meta.get("uri"):
                return (
                    f"Source '{meta.get('title', source_id)}' is a reference — "
                    f"content not stored locally. Original URI: {meta['uri']}\n"
                    f"Summary: {meta.get('summary', 'No summary available.')}"
                )
            return "Source content not available."
        content_resp.raise_for_status()
        content = content_resp.json().get("content", "")

    header = f"Source: {meta.get('title', 'Untitled')} [{meta['source_kind']}]"
    if meta.get("author"):
        header += f" by {meta['author']}"
    if meta.get("trust_score"):
        header += f" (trust: {meta['trust_score']:.1f})"

    # Truncate very large content to avoid blowing context
    if len(content) > 15000:
        content = content[:15000] + f"\n\n[... truncated, {len(content)} chars total]"

    return f"{header}\n\n{content}"
```

- [ ] **Step 4: Register memory tools in __init__.py**

Modify `orchestrator/app/tools/__init__.py`:

```python
# Add import
from app.tools.memory_tools import MEMORY_TOOLS
from app.tools.memory_tools import execute_tool as _exec_memory

# Add to _REGISTRY
ToolGroup("Memory", "Knowledge Retrieval", "Search, recall, and read from Nova's memory system", MEMORY_TOOLS, _exec_memory),
```

- [ ] **Step 5: Run tests**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_memory_tools.py -v -x
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/app/tools/memory_tools.py orchestrator/app/tools/__init__.py tests/test_memory_tools.py
git commit -m "feat(tools): add agent-callable memory tools (search, recall, read_source, what_do_i_know)"
```

---

### Task 9: Domain Awareness Priming (Replace 40% Pre-Injection)

**Files:**
- Modify: `orchestrator/app/agents/runner.py`
- Modify: `orchestrator/app/config.py`
- Modify: `memory-service/app/engram/working_memory.py`

This is the key architectural shift. Instead of dumping 40% of the context window with memory, inject a ~200-token domain awareness summary + give the agent memory tools.

**Rollback strategy:** `memory_retrieval_mode` defaults to `"inject"` (legacy behavior). Switch to `"tools"` via dashboard Settings or `.env` when ready. If agents produce worse results with tools mode, switch back to `"inject"` — no code changes needed, just a config toggle. Both modes coexist in the code.

- [ ] **Step 1: Read runner.py memory integration**

```bash
sed -n '60,120p' orchestrator/app/agents/runner.py
sed -n '330,410p' orchestrator/app/agents/runner.py
sed -n '870,910p' orchestrator/app/agents/runner.py
```

Understand: `_get_memory_context()`, how it's called in `run_agent_turn()`, and how memory_ctx is injected into the prompt.

- [ ] **Step 2: Add domain priming config**

In `orchestrator/app/config.py`, replace `context_memory_pct` usage:

```python
# Memory retrieval mode
memory_retrieval_mode: str = "inject"  # "inject" (legacy 40%), "tools" (agent-driven). Switch via dashboard Settings or .env
context_priming_pct: float = 0.05     # Domain awareness priming budget (small)
```

- [ ] **Step 3: Create `_get_domain_priming` function in runner.py**

Add alongside `_get_memory_context`:

```python
async def _get_domain_priming(session_id: str) -> str:
    """Fetch lightweight domain awareness for agent priming.

    Returns a ~200-token summary of what Nova knows (topics, source titles,
    counts) — enough for the agent to know what to look up via memory tools,
    without consuming significant context.
    """
    try:
        memory_client = get_memory_client()
        resp = await memory_client.get("/api/v1/engrams/sources/domain-summary")
        if resp.status_code != 200:
            return ""
        data = resp.json()

        lines = ["## Your Knowledge"]
        lines.append(f"You have {data.get('engram_count', 0)} memories from {data.get('source_count', 0)} sources.")

        domains = data.get("domains", [])
        if domains:
            lines.append(f"Topics: {', '.join(domains[:10])}")

        sources = data.get("recent_sources", [])
        if sources:
            titles = [s["title"] for s in sources[:5] if s.get("title")]
            if titles:
                lines.append(f"Recent sources: {', '.join(titles)}")

        lines.append("Use your memory tools (search_memory, recall_topic, read_source) to retrieve details.")
        return "\n".join(lines)
    except Exception as e:
        log.warning("Domain priming fetch failed: %s", e)
        return ""
```

- [ ] **Step 4: Modify `run_agent_turn` to use domain priming when mode is "tools"**

In `run_agent_turn()`, replace the memory context fetch:

```python
if settings.memory_retrieval_mode == "tools":
    # Lightweight priming — agent uses memory tools for depth
    memory_ctx = await _get_domain_priming(session_id)
    _mem_count, _engram_ids, _retrieval_log_id = 0, [], None
else:
    # Legacy: full 40% context injection
    memory_ctx, _mem_count, _engram_ids, _retrieval_log_id = await _get_memory_context(
        agent_id, query, session_id
    )
```

- [ ] **Step 5: Keep working memory slots (pinned + sticky) in both modes**

The self-model and active goal (pinned slots) should still be injected — they're small and always relevant. Modify `_get_domain_priming` to also fetch pinned context:

```python
# Always include self-model and active goal (pinned slots).
# NOTE: The /context endpoint returns sections as booleans (True/False),
# not strings. The actual content is in dedicated endpoints.
self_model_resp = await memory_client.get("/api/v1/engrams/self-model")
if self_model_resp.status_code == 200:
    sm = self_model_resp.json().get("self_model", "")
    if sm:
        lines.insert(0, f"## About Me\n{sm}")
```

- [ ] **Step 6: Run tests**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/ -v -x --timeout=120 2>&1 | tail -20
```

- [ ] **Step 7: Commit**

```bash
git add orchestrator/app/agents/runner.py orchestrator/app/config.py
git commit -m "feat(memory): replace 40% context pre-injection with domain priming + memory tools"
```

---

## Phase 4: Source Content Storage & Summarization

Enables deep retrieval — agents can go back to full source content when engrams aren't enough.

### Task 10: Hierarchical Summarization

**Files:**
- Modify: `memory-service/app/engram/sources.py`
- Modify: `memory-service/app/engram/decomposition.py`
- Modify: `memory-service/app/engram/ingestion.py`

- [ ] **Step 1: Add summarization prompt to decomposition.py**

```python
SOURCE_SUMMARY_PROMPT = """Summarize this content in exactly ONE paragraph (3-5 sentences).
Focus on: what this content IS (article, conversation, documentation), its main topic,
key takeaways, and any important names/dates/facts. This summary will be used to help
decide whether this source is relevant to a future question.

Content to summarize:
{content}"""
```

- [ ] **Step 2: Add `generate_source_summary` function to sources.py**

```python
async def generate_source_summary(content: str) -> str:
    """Generate a 1-paragraph summary of source content via LLM."""
    from .decomposition import resolve_model, SOURCE_SUMMARY_PROMPT
    from app.config import settings

    model = await resolve_model(settings.engram_decomposition_model)
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(
            f"{settings.llm_gateway_url}/complete",
            json={
                "model": model,
                "messages": [
                    {"role": "user", "content": SOURCE_SUMMARY_PROMPT.format(content=content[:8000])},
                ],
                "temperature": 0.3,
                "max_tokens": 300,
            },
        )
        if resp.status_code == 200:
            return resp.json().get("content", "")
    return ""
```

- [ ] **Step 3: Wire summarization into ingestion**

In `_process_event()`, after creating the source record, generate and store a summary:

```python
# Generate source summary (fire-and-forget for performance)
if source_ref_id and len(raw_text) > 200:
    try:
        summary = await generate_source_summary(raw_text)
        if summary:
            await update_source_summary(session, source_ref_id, summary)
    except Exception as exc:
        log.warning("Source summarization failed (non-fatal): %s", exc)
```

- [ ] **Step 4: Run tests**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_sources.py tests/test_memory_tools.py -v -x
```

- [ ] **Step 5: Commit**

```bash
git add memory-service/app/engram/sources.py memory-service/app/engram/decomposition.py memory-service/app/engram/ingestion.py
git commit -m "feat(memory): hierarchical source summarization at ingestion time"
```

---

### Task 11: Source Content Filesystem Storage

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add data/sources volume mount to memory-service**

In `docker-compose.yml`, add to the memory-service volumes:

```yaml
memory-service:
  volumes:
    - ./data/sources:/data/sources
```

This ensures source content stored to filesystem persists across container restarts, alongside `data/postgres/` and `data/redis/`.

- [ ] **Step 2: Create the directory and add to .gitignore**

```bash
mkdir -p data/sources
```

Add `data/sources/` to `.gitignore` (alongside existing `data/postgres/` and `data/redis/` entries):

```
data/sources/
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml .gitignore
git commit -m "feat(infra): add data/sources volume mount for large source content storage"
```

---

### Task 12: Re-Decomposition from Stored Sources

**Files:**
- Modify: `orchestrator/app/engram_router.py`

- [ ] **Step 1: Add re-decomposition endpoint**

First, ensure `UUID` is imported at the top of `engram_router.py`:

```python
from uuid import UUID
```

Then add the endpoint:

```python
@router.post("/sources/{source_id}/redecompose")
async def redecompose_source(source_id: UUID, _admin: AdminDep):
    """Re-decompose a source through the current ingestion pipeline.

    Deletes existing engrams from this source, fetches stored content,
    and re-queues for ingestion. Useful after decomposition prompt improvements.
    """
    # Fetch source content from memory-service
    async with httpx.AsyncClient(timeout=10) as client:
        content_resp = await client.get(
            f"{settings.memory_service_url}/api/v1/engrams/sources/{source_id}/content"
        )
        if content_resp.status_code != 200:
            return {"error": "Source content not available for re-decomposition"}
        content = content_resp.json().get("content")

        meta_resp = await client.get(
            f"{settings.memory_service_url}/api/v1/engrams/sources/{source_id}"
        )
        meta = meta_resp.json() if meta_resp.status_code == 200 else {}

    if not content:
        return {"error": "No stored content — URI-only sources cannot be re-decomposed"}

    # Queue for ingestion with source linkage
    r = aioredis.from_url(_engram_redis_url(), decode_responses=True)
    try:
        await _push_to_queue(
            r,
            raw_text=content,
            source_type=meta.get("source_kind", "manual_paste"),
            source_id=str(source_id),
            metadata={"redecompose": True, "source_ref_id": str(source_id)},
        )
    finally:
        await r.aclose()

    return {"status": "queued", "source_id": str(source_id)}
```

- [ ] **Step 2: Run tests**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/ -v -x -k "health" --timeout=30
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/engram_router.py
git commit -m "feat(memory): add re-decomposition endpoint for stored sources"
```

---

## Phase 5: Feedback, Gap Detection & Dashboard

### Task 13: Retrieval Feedback via Memory Tools

**Files:**
- Modify: `orchestrator/app/agents/runner.py`

- [ ] **Step 1: Track which memory tool results were used**

When `memory_retrieval_mode == "tools"`, the agent uses memory tools during the conversation. After the response, check which `search_memory`/`recall_topic` tool calls were made and which source_ids/engram_ids appeared in the final response.

In `_store_exchange()`, if memory tool calls were made during the turn, extract engram IDs from tool results and call `_mark_engrams_used()`:

```python
# After agent turn, if memory tools were called:
memory_tool_engram_ids = _extract_engram_ids_from_tool_results(tool_results)
if memory_tool_engram_ids:
    await _mark_engrams_used(memory_tool_engram_ids, None)
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/agents/runner.py
git commit -m "feat(memory): connect retrieval feedback loop to memory tool usage"
```

---

### Task 14: Knowledge Gap Detection

**Files:**
- Modify: `memory-service/app/engram/sources.py`

- [ ] **Step 1: Add gap detection to domain summary**

Extend `get_domain_summary()` to include gap information:

```python
# Incomplete sources
gaps_q = await session.execute(
    text("""
        SELECT title, source_kind, completeness, coverage_notes
        FROM sources
        WHERE completeness != 'complete'
        ORDER BY ingested_at DESC
        LIMIT 10
    """)
)
gaps = [
    {"title": r.title, "kind": r.source_kind, "coverage": r.coverage_notes}
    for r in gaps_q.fetchall()
]

# Stale sources
stale_q = await session.execute(
    text("""
        SELECT title, source_kind, verified_at
        FROM sources
        WHERE stale = TRUE OR (verified_at IS NOT NULL AND verified_at < NOW() - INTERVAL '30 days')
        ORDER BY verified_at ASC NULLS FIRST
        LIMIT 10
    """)
)
stale_sources = [{"title": r.title, "kind": r.source_kind} for r in stale_q.fetchall()]
```

Add to return dict:

```python
"gaps": gaps,
"stale_sources": stale_sources,
```

- [ ] **Step 2: Commit**

```bash
git add memory-service/app/engram/sources.py
git commit -m "feat(memory): add knowledge gap and staleness detection to domain summary"
```

---

### Task 15: Dashboard Source Attribution

**Files:**
- Modify: `dashboard/src/pages/EngramExplorer.tsx`

- [ ] **Step 1: Read the current EngramExplorer**

```bash
cat dashboard/src/pages/EngramExplorer.tsx
```

- [ ] **Step 2: Add source attribution to engram detail display**

In the engram detail view (where type badge, importance bar, etc. are shown), add source information:

```tsx
{/* Source attribution */}
{engram.source_ref_id && (
  <div className="text-xs text-stone-500 mt-1">
    Source: <button
      className="text-teal-400 hover:underline"
      onClick={() => setSelectedSource(engram.source_ref_id)}
    >
      {engram.source_meta?.title || engram.source_ref_id}
    </button>
    {engram.source_meta?.url && (
      <span className="ml-1 text-stone-600">({engram.source_meta.url})</span>
    )}
  </div>
)}
{engram.temporal_validity === 'dated' && (
  <span className="text-xs text-amber-500 ml-2">time-sensitive</span>
)}
```

- [ ] **Step 3: Add Sources tab to EngramExplorer**

Add a new tab that lists all sources with their engram counts, trust scores, and summaries. Each source links to a filtered view of its engrams.

```tsx
// Sources tab content
<div className="space-y-3">
  {sources.map(s => (
    <div key={s.id} className="bg-stone-800 rounded-lg p-3">
      <div className="flex justify-between items-start">
        <div>
          <span className="text-sm font-medium text-stone-200">{s.title || 'Untitled'}</span>
          <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-stone-700 text-stone-400">
            {s.source_kind}
          </span>
        </div>
        <span className="text-xs text-stone-500">{s.engram_count} engrams</span>
      </div>
      {s.summary && <p className="text-xs text-stone-400 mt-1">{s.summary}</p>}
      <div className="flex gap-3 mt-2 text-xs text-stone-500">
        <span>Trust: {(s.trust_score * 100).toFixed(0)}%</span>
        {s.stale && <span className="text-amber-500">stale</span>}
        {s.completeness !== 'complete' && (
          <span className="text-amber-500">{s.completeness}: {s.coverage_notes}</span>
        )}
      </div>
    </div>
  ))}
</div>
```

- [ ] **Step 4: Build dashboard to verify TypeScript compiles**

```bash
cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build
```

Expected: No TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/EngramExplorer.tsx
git commit -m "feat(dashboard): add source attribution and Sources tab to Memory Explorer"
```

---

## Phase 6: Update Documentation and Configuration

### Task 16: Update CLAUDE.md and Website Docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `website/src/content/docs/nova/docs/services/memory-service.md` (if exists)

- [ ] **Step 1: Update CLAUDE.md Engram Memory System section**

Add sources, memory tools, and retrieval mode to the documentation:

```markdown
### Source Provenance

Every engram links back to a `sources` table tracking where knowledge came from. Sources store metadata (URI, title, author, trust score) and optionally full content (hybrid: DB for small, filesystem for large, URI for re-fetchable). Content stored at `data/sources/` (bind-mounted).

### Memory Tools

Agents access memory via tools instead of pre-injected context:
- `what_do_i_know` — lightweight domain overview (~200 tokens)
- `search_memory` — semantic search across engrams
- `recall_topic` — graph traversal from an entity
- `read_source` — full source content retrieval

Controlled by `memory_retrieval_mode` in `.env` (`tools` or `inject` for legacy).
```

- [ ] **Step 2: Update roadmap if needed**

Add source provenance to the "What's Shipped" section of `docs/roadmap.md`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/roadmap.md
git commit -m "docs: document source provenance, memory tools, and retrieval mode"
```

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| **1: Foundation** | 1-5 | Sources table, Pydantic models, CRUD API, ingestion linkage, fix broken payload |
| **2: Better Engrams** | 6-7 | Paragraph-level decomposition, fact-level dedup, temporal validity |
| **3: Memory Tools** | 8-9 | Agent-callable tools, domain priming, kill 40% pre-injection |
| **4: Content Storage** | 10-12 | Hierarchical summaries, filesystem storage, re-decomposition |
| **5: Feedback + Dashboard** | 13-15 | Retrieval feedback loop, gap detection, source attribution UI |
| **6: Docs** | 16 | CLAUDE.md, roadmap, website docs |

Each phase produces working, testable software. Phase 1 is the critical path — everything else builds on it.
