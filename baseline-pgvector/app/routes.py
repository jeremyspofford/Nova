"""
Baseline pgvector memory API routes.

Implements the minimal memory provider interface:
- POST /context — retrieve relevant memory for a query
- POST /ingest — store new text in memory
- POST /mark-used — no-op acknowledgement (baseline doesn't learn)
- GET /stats — provider metadata and item count
"""
from __future__ import annotations

import logging
from uuid import UUID

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import settings
from app.db import get_pool

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


# ── Request / Response Models ────────────────────────────────────────────


class ContextRequest(BaseModel):
    query: str
    query_embedding: list[float] | None = None
    top_k: int = Field(default=10, ge=1, le=100)


class ContextResponse(BaseModel):
    context: str
    total_tokens: int
    engram_ids: list[str]


class MemoryIngestRequest(BaseModel):
    raw_text: str
    source_type: str = "chat"
    source_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class MemoryIngestResponse(BaseModel):
    items_created: int


class MarkUsedRequest(BaseModel):
    engram_ids: list[str]
    session_id: str = ""
    was_useful: bool = True


class ProviderStats(BaseModel):
    provider_name: str
    total_items: int
    capabilities: list[str]


# ── Embedding helper ─────────────────────────────────────────────────────


async def _get_embedding(text: str) -> list[float]:
    """Call llm-gateway /embed to get an embedding vector."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.llm_gateway_url}/embed",
            json={
                "model": settings.embedding_model,
                "texts": [text],
                "dimensions": settings.embedding_dimensions,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embeddings"][0]


# ── Chunking ─────────────────────────────────────────────────────────────


def _chunk_text(text: str) -> list[str]:
    """Split text into ~500 char chunks with 100 char overlap."""
    size = settings.chunk_size
    overlap = settings.chunk_overlap
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/context", response_model=ContextResponse)
async def get_context(req: ContextRequest):
    """Retrieve relevant memory items by cosine similarity."""
    # Get or compute embedding
    if req.query_embedding:
        embedding = req.query_embedding
    else:
        embedding = await _get_embedding(req.query)

    vec_literal = "[" + ",".join(str(v) for v in embedding) + "]"

    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, content, source_type, 1 - (embedding <=> $1::halfvec) AS score
        FROM baseline_pgvector_items
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> $1::halfvec
        LIMIT $2
        """,
        vec_literal,
        req.top_k,
    )

    if not rows:
        return ContextResponse(context="", total_tokens=0, engram_ids=[])

    # Format as numbered markdown list
    lines = []
    engram_ids = []
    for i, row in enumerate(rows, 1):
        score = round(float(row["score"]), 4)
        lines.append(f"{i}. [{score}] {row['content']}")
        engram_ids.append(str(row["id"]))

    context = "\n".join(lines)
    # Rough token estimate: ~4 chars per token
    total_tokens = len(context) // 4

    return ContextResponse(
        context=context,
        total_tokens=total_tokens,
        engram_ids=engram_ids,
    )


@router.post("/ingest", response_model=MemoryIngestResponse, status_code=201)
async def ingest_memory(req: MemoryIngestRequest):
    """Chunk text, embed each chunk, and store in pgvector."""
    chunks = _chunk_text(req.raw_text)
    pool = get_pool()
    items_created = 0

    for chunk in chunks:
        try:
            embedding = await _get_embedding(chunk)
            vec_literal = "[" + ",".join(str(v) for v in embedding) + "]"

            await pool.execute(
                """
                INSERT INTO baseline_pgvector_items
                    (content, embedding, source_type, source_id, metadata)
                VALUES ($1, $2::halfvec, $3, $4, $5::jsonb)
                """,
                chunk,
                vec_literal,
                req.source_type,
                req.source_id,
                "{}",  # metadata as JSON string
            )
            items_created += 1
        except Exception:
            log.warning("Failed to ingest chunk", exc_info=True)

    return MemoryIngestResponse(items_created=items_created)


@router.post("/mark-used")
async def mark_used(req: MarkUsedRequest):
    """Acknowledge mark-used request. Baseline doesn't learn from feedback."""
    log.debug(
        "mark-used received: %d engrams, useful=%s",
        len(req.engram_ids),
        req.was_useful,
    )
    return {"status": "ok"}


@router.get("/stats", response_model=ProviderStats)
async def get_stats():
    """Return provider metadata and total item count."""
    pool = get_pool()
    count = await pool.fetchval("SELECT count(*) FROM baseline_pgvector_items")
    return ProviderStats(
        provider_name="pgvector-only",
        total_items=count or 0,
        capabilities=[],
    )
