"""
Memory Service FastAPI router — implements the 9 core endpoints from the architecture doc.
All endpoints accept text, return text. Embeddings are internal.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nova_contracts import (
    BulkStoreRequest,
    BulkStoreResponse,
    GetContextRequest,
    GetContextResponse,
    MemoryResult,
    MemoryTier,
    SearchMemoryRequest,
    SearchMemoryResponse,
    StoreMemoryRequest,
    StoreMemoryResponse,
    UpdateMemoryRequest,
)

from app.db.database import get_db
from app.embedding import get_embedding
from app.retrieval import hybrid_search

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/memories", tags=["memories"])

TIER_TABLES = {
    MemoryTier.working: "working_memories",
    MemoryTier.episodic: "episodic_memories",
    MemoryTier.semantic: "semantic_memories",
    MemoryTier.procedural: "procedural_memories",
}


@router.post("", response_model=StoreMemoryResponse, status_code=201)
async def store_memory(req: StoreMemoryRequest):
    async with get_db() as session:
        embedding = await get_embedding(req.content, session)
        table = TIER_TABLES[req.tier]
        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

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
        )

    results = [
        MemoryResult(
            id=UUID(r.id),
            content=r.content,
            tier=MemoryTier.episodic,  # tier resolution from table in full impl
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
        for tier, table in TIER_TABLES.items():
            result = await session.execute(
                text(f"SELECT id, content, metadata, created_at FROM {table} WHERE id = :id"),
                {"id": str(memory_id)},
            )
            row = result.fetchone()
            if row:
                return MemoryResult(
                    id=row.id,
                    content=row.content,
                    tier=tier,
                    score=1.0,
                    metadata=dict(row.metadata),
                    created_at=row.created_at,
                )
    raise HTTPException(status_code=404, detail="Memory not found")


@router.patch("/{memory_id}", status_code=204)
async def update_memory(memory_id: UUID, req: UpdateMemoryRequest):
    async with get_db() as session:
        for tier, table in TIER_TABLES.items():
            row = await session.execute(
                text(f"SELECT id FROM {table} WHERE id = :id"),
                {"id": str(memory_id)},
            )
            if not row.fetchone():
                continue

            if req.content:
                embedding = await get_embedding(req.content, session)
                embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
                # Only semantic_memories and procedural_memories have updated_at;
                # working_memories uses expires_at, episodic_memories is append-only
                has_updated_at = table in ("semantic_memories", "procedural_memories")
                set_clause = "content = :content, embedding = :emb::halfvec"
                if has_updated_at:
                    set_clause += ", updated_at = now()"
                await session.execute(
                    text(f"UPDATE {table} SET {set_clause} WHERE id = :id"),
                    {"content": req.content, "emb": embedding_str, "id": str(memory_id)},
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
        for tier, table in TIER_TABLES.items():
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
                table = TIER_TABLES[mem_req.tier]
                embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
                result = await session.execute(
                    text(f"""
                        INSERT INTO {table} (agent_id, content, embedding, metadata)
                        VALUES (:agent_id, :content, :embedding::halfvec, :metadata::jsonb)
                        RETURNING id
                    """),
                    {
                        "agent_id": mem_req.agent_id,
                        "content": mem_req.content,
                        "embedding": embedding_str,
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
