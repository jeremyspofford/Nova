"""
Memory Service FastAPI router — implements the 9 core endpoints from the architecture doc.
All endpoints accept text, return text. Embeddings are internal.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nova_contracts import (
    BrowseMemoryItem,
    BrowseMemoryResponse,
    BulkStoreRequest,
    BulkStoreResponse,
    GetContextRequest,
    GetContextResponse,
    MemoryResult,
    MemoryTier,
    SaveFactRequest,
    SaveFactResponse,
    SearchMemoryRequest,
    SearchMemoryResponse,
    StoreMemoryRequest,
    StoreMemoryResponse,
    UpdateMemoryRequest,
)

from app.db.database import get_db
from app.embedding import get_embedding, get_embeddings_batch
from app.retrieval import TIER_TABLES, _actr_confidence, hybrid_search, tier_table, to_pg_vector
from app.service import save_fact_internal

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/memories", tags=["memories"])


@router.get("/browse", response_model=BrowseMemoryResponse)
async def browse_memories_v2(
    tier: MemoryTier | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Browse memories with pagination. Supports all tiers with semantic-specific fields."""
    tiers_to_query = [tier] if tier else [
        MemoryTier.semantic, MemoryTier.procedural, MemoryTier.episodic
    ]
    items: list[BrowseMemoryItem] = []
    total = 0

    async with get_db() as session:
        for t in tiers_to_query:
            table = tier_table(t)
            where_parts = []
            params: dict = {}
            if agent_id:
                where_parts.append("agent_id = :agent_id")
                params["agent_id"] = agent_id
            where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            # Count
            count_row = await session.execute(
                text(f"SELECT count(*) FROM {table} {where_clause}"),
                params,
            )
            total += count_row.scalar()

            # Fetch — include semantic-specific columns when applicable
            is_semantic = t == MemoryTier.semantic
            extra_cols = ", project_id, category, key, base_confidence, last_accessed_at" if is_semantic else ""
            has_updated = t in (MemoryTier.semantic, MemoryTier.procedural)
            updated_col = ", updated_at" if has_updated else ""

            rows = await session.execute(
                text(f"""
                    SELECT id, agent_id, content, metadata, created_at{updated_col}{extra_cols}
                    FROM {table}
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {**params, "limit": limit, "offset": offset},
            )
            for row in rows:
                item = BrowseMemoryItem(
                    id=row.id,
                    content=row.content,
                    tier=t,
                    agent_id=row.agent_id,
                    metadata=dict(row.metadata),
                    created_at=row.created_at,
                    updated_at=getattr(row, 'updated_at', None),
                )
                if is_semantic:
                    item.project_id = row.project_id
                    item.category = row.category
                    item.key = row.key
                    item.base_confidence = row.base_confidence
                    item.last_accessed_at = row.last_accessed_at
                    item.effective_confidence = _actr_confidence(
                        row.base_confidence, row.last_accessed_at
                    )
                items.append(item)

    items.sort(key=lambda r: r.created_at, reverse=True)
    return BrowseMemoryResponse(items=items[:limit], total=total, offset=offset, limit=limit)


@router.post("/facts", response_model=SaveFactResponse, status_code=201)
async def save_fact(req: SaveFactRequest):
    """Upsert a semantic fact with deduplication by (project_id, category, key)."""
    async with get_db() as session:
        result = await save_fact_internal(
            session=session,
            agent_id=req.agent_id,
            project_id=req.project_id,
            category=req.category,
            key=req.key,
            content=req.content,
            base_confidence=req.base_confidence,
            metadata=req.metadata,
        )
    return SaveFactResponse(
        project_id=req.project_id,
        category=req.category,
        key=req.key,
        **result,
    )


@router.post("", response_model=StoreMemoryResponse, status_code=201)
async def store_memory(req: StoreMemoryRequest):
    async with get_db() as session:
        embedding = await get_embedding(req.content, session)
        table = tier_table(req.tier)
        embedding_str = to_pg_vector(embedding)

        params: dict = {
            "agent_id": req.agent_id,
            "content": req.content,
            "embedding": embedding_str,
            "metadata": req.metadata,
        }

        # working_memories is the only tier with expires_at — add it to INSERT when TTL set
        if req.ttl_seconds and req.tier == MemoryTier.working:
            cols = "agent_id, content, embedding, metadata, expires_at"
            vals = ":agent_id, :content, :embedding::halfvec, :metadata::jsonb, now() + make_interval(secs => :ttl)"
            params["ttl"] = req.ttl_seconds
        else:
            cols = "agent_id, content, embedding, metadata"
            vals = ":agent_id, :content, :embedding::halfvec, :metadata::jsonb"

        result = await session.execute(
            text(f"""
                INSERT INTO {table} ({cols})
                VALUES ({vals})
                RETURNING id, created_at
            """),
            params,
        )
        row = result.fetchone()

    return StoreMemoryResponse(
        id=row.id,
        agent_id=req.agent_id,
        tier=req.tier,
        created_at=row.created_at,
    )


@router.post("/search", response_model=SearchMemoryResponse)
async def search_memories(req: SearchMemoryRequest):
    async with get_db() as session:
        embedding = await get_embedding(req.query, session)
        tier_names = [t.value for t in req.tiers]

        fused = await hybrid_search(
            session=session,
            agent_id=req.agent_id,
            query_embedding=embedding,
            query_text=req.query,
            tiers=tier_names,
            limit=req.limit,
            vector_weight=req.vector_weight,
            keyword_weight=req.keyword_weight,
            metadata_filter=req.metadata_filter or None,
        )

    results = [
        MemoryResult(
            id=UUID(r.id),
            content=r.content,
            tier=MemoryTier(r.tier) if r.tier else MemoryTier.episodic,
            score=r.score,
            metadata=r.metadata,
            created_at=r.created_at,
        )
        for r in fused
    ]
    return SearchMemoryResponse(results=results, query=req.query, total_found=len(results))


@router.get("/{memory_id}", response_model=MemoryResult)
async def get_memory(memory_id: UUID):
    async with get_db() as session:
        # Search across all tiers (working memory first — hot cache)
        for tier_str, table in TIER_TABLES.items():
            result = await session.execute(
                text(f"SELECT id, content, metadata, created_at FROM {table} WHERE id = :id"),
                {"id": str(memory_id)},
            )
            row = result.fetchone()
            if row:
                return MemoryResult(
                    id=row.id,
                    content=row.content,
                    tier=MemoryTier(tier_str),
                    score=1.0,
                    metadata=dict(row.metadata),
                    created_at=row.created_at,
                )
    raise HTTPException(status_code=404, detail="Memory not found")


@router.patch("/{memory_id}", status_code=204)
async def update_memory(memory_id: UUID, req: UpdateMemoryRequest):
    async with get_db() as session:
        for tier_str, table in TIER_TABLES.items():
            row = await session.execute(
                text(f"SELECT id FROM {table} WHERE id = :id"),
                {"id": str(memory_id)},
            )
            if not row.fetchone():
                continue

            if req.content:
                embedding = await get_embedding(req.content, session)
                # Only semantic_memories and procedural_memories have updated_at;
                # working_memories uses expires_at, episodic_memories is append-only
                has_updated_at = table in ("semantic_memories", "procedural_memories")
                set_clause = "content = :content, embedding = :emb::halfvec"
                if has_updated_at:
                    set_clause += ", updated_at = now()"
                await session.execute(
                    text(f"UPDATE {table} SET {set_clause} WHERE id = :id"),
                    {"content": req.content, "emb": to_pg_vector(embedding), "id": str(memory_id)},
                )
            if req.metadata is not None:
                await session.execute(
                    text(f"UPDATE {table} SET metadata = :meta::jsonb WHERE id = :id"),
                    {"meta": req.metadata, "id": str(memory_id)},
                )
            return

    raise HTTPException(status_code=404, detail="Memory not found")


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: UUID):
    async with get_db() as session:
        deleted = False
        for tier_str, table in TIER_TABLES.items():
            result = await session.execute(
                text(f"DELETE FROM {table} WHERE id = :id RETURNING id"),
                {"id": str(memory_id)},
            )
            if result.fetchone():
                deleted = True
                break

    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")


@router.post("/bulk", response_model=BulkStoreResponse, status_code=201)
async def bulk_store(req: BulkStoreRequest):
    stored = []
    failed = []

    async with get_db() as session:
        for i, mem_req in enumerate(req.memories):
            try:
                embedding = await get_embedding(mem_req.content, session)
                table = tier_table(mem_req.tier)
                result = await session.execute(
                    text(f"""
                        INSERT INTO {table} (agent_id, content, embedding, metadata)
                        VALUES (:agent_id, :content, :embedding::halfvec, :metadata::jsonb)
                        RETURNING id
                    """),
                    {
                        "agent_id": mem_req.agent_id,
                        "content": mem_req.content,
                        "embedding": to_pg_vector(embedding),
                        "metadata": mem_req.metadata,
                    },
                )
                stored.append(result.fetchone().id)
            except Exception as e:
                log.error("Bulk store failed for item %d: %s", i, e)
                failed.append(i)

    return BulkStoreResponse(stored=stored, failed=failed)


# Context assembly endpoint — assembles agent context from memories
context_router = APIRouter(prefix="/api/v1/agents", tags=["context"])


@context_router.post("/{agent_id}/context", response_model=GetContextResponse)
async def get_agent_context(agent_id: str, req: GetContextRequest):
    """
    Assemble the memory context window for an agent's next LLM call.
    Retrieves and ranks memories, then fits them into the token budget.
    """
    search_req = SearchMemoryRequest(
        agent_id=agent_id,
        query=req.query,
        tiers=[MemoryTier.episodic, MemoryTier.semantic, MemoryTier.procedural],
        limit=50,  # Fetch more than needed, then trim to token budget
    )

    search_resp = await search_memories(search_req)

    # Greedy token packing — highest-scoring memories first
    # Rough estimate: 1 token ≈ 4 characters
    selected = []
    tokens_used = 0
    for mem in search_resp.results:
        estimated_tokens = len(mem.content) // 4
        if tokens_used + estimated_tokens > req.max_tokens:
            break
        selected.append(mem)
        tokens_used += estimated_tokens

    return GetContextResponse(
        agent_id=agent_id,
        memories=selected,
        total_tokens_estimated=tokens_used,
    )
