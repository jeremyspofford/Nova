"""
Memory API endpoints — the benchmark-compatible interface.

POST /api/v1/memory/context   — retrieve relevant context for a query
POST /api/v1/memory/ingest    — ingest raw text into memory
POST /api/v1/memory/mark-used — no-op for this baseline
GET  /api/v1/memory/stats     — provider stats
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.chunker import chunk_markdown
from app.config import settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# In-memory storage
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    id: str
    content: str
    embedding: list[float]
    source_file: str | None
    source_type: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


chunks: list[Chunk] = []


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ContextRequest(BaseModel):
    query: str
    query_embedding: list[float] | None = None
    top_k: int = 10

class ContextResult(BaseModel):
    id: str
    content: str
    score: float
    source_file: str | None
    source_type: str

class ContextResponse(BaseModel):
    results: list[ContextResult]
    context_text: str
    total_chunks: int

class MemoryIngestRequest(BaseModel):
    raw_text: str
    source_file: str | None = None
    source_type: str = "dynamic"

class MemoryIngestResponse(BaseModel):
    chunks_created: int
    chunk_ids: list[str]

class ProviderStats(BaseModel):
    provider_name: str
    total_items: int
    capabilities: list[str]


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

async def _embed(text: str) -> list[float]:
    """Get an embedding vector from llm-gateway."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.llm_gateway_url}/embed",
            json={"text": text},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embedding"]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr, b_arr = np.array(a), np.array(b)
    denom = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if denom == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / denom)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/context", response_model=ContextResponse)
async def get_context(req: ContextRequest):
    """Retrieve top-K chunks by cosine similarity."""
    if not chunks:
        return ContextResponse(results=[], context_text="", total_chunks=0)

    # Get or compute query embedding
    if req.query_embedding is not None:
        q_emb = req.query_embedding
    else:
        try:
            q_emb = await _embed(req.query)
        except Exception as e:
            log.error("Failed to embed query: %s", e)
            raise HTTPException(status_code=502, detail=f"Embedding failed: {e}")

    # Score all chunks
    scored = [
        (chunk, _cosine_similarity(q_emb, chunk.embedding))
        for chunk in chunks
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[: req.top_k]

    results = [
        ContextResult(
            id=c.id,
            content=c.content,
            score=score,
            source_file=c.source_file,
            source_type=c.source_type,
        )
        for c, score in top
    ]

    # Format as markdown for LLM consumption
    context_parts = []
    for r in results:
        header = f"[{r.source_type}"
        if r.source_file:
            header += f": {r.source_file}"
        header += f" | score={r.score:.3f}]"
        context_parts.append(f"{header}\n{r.content}")

    return ContextResponse(
        results=results,
        context_text="\n\n---\n\n".join(context_parts),
        total_chunks=len(chunks),
    )


@router.post("/ingest", response_model=MemoryIngestResponse)
async def ingest(req: MemoryIngestRequest):
    """Chunk text, embed each chunk, store in memory."""
    text_chunks = chunk_markdown(req.raw_text, source_file=req.source_file)
    if not text_chunks:
        return MemoryIngestResponse(chunks_created=0, chunk_ids=[])

    new_ids: list[str] = []
    for text in text_chunks:
        try:
            emb = await _embed(text)
        except Exception as e:
            log.warning("Failed to embed chunk (skipping): %s", e)
            continue

        chunk_id = str(uuid.uuid4())
        chunks.append(Chunk(
            id=chunk_id,
            content=text,
            embedding=emb,
            source_file=req.source_file,
            source_type=req.source_type,
        ))
        new_ids.append(chunk_id)

    log.info("Ingested %d chunks from source=%s", len(new_ids), req.source_file or "dynamic")
    return MemoryIngestResponse(chunks_created=len(new_ids), chunk_ids=new_ids)


@router.post("/mark-used")
async def mark_used():
    """No-op -- this baseline doesn't learn from usage feedback."""
    return {"status": "ok"}


@router.get("/stats", response_model=ProviderStats)
async def stats():
    """Return provider metadata and chunk count."""
    return ProviderStats(
        provider_name="markdown-context",
        total_items=len(chunks),
        capabilities=[],
    )
