"""
Baseline Mem0 wrapper — routes.

Implements Nova's Memory Provider Interface by delegating to the Mem0 SDK.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from nova_contracts.memory import (
    ContextRequest,
    ContextResponse,
    MarkUsedRequest,
    MemoryIngestRequest,
    MemoryIngestResponse,
    ProviderStats,
)

log = logging.getLogger("baseline-mem0")

# ── Health endpoints ────────────────────────────────────────────────────────

health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get("/live")
async def liveness():
    return {"status": "alive"}


@health_router.get("/ready")
async def readiness(request: Request):
    mem0_ok = getattr(request.app.state, "mem0_ready", False)
    return {
        "status": "ready" if mem0_ok else "degraded",
        "checks": {"mem0": "ok" if mem0_ok else "not initialized"},
    }


@health_router.get("/startup")
async def startup():
    return {"status": "started"}


# ── Memory Provider Interface ──────────────────────────────────────────────

memory_router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


def _get_mem0(request: Request):
    """Get the Mem0 instance from app state, or None if not initialized."""
    return getattr(request.app.state, "mem0", None)


@memory_router.post("/context", response_model=ContextResponse)
async def retrieve_context(body: ContextRequest, request: Request):
    """Retrieve relevant context for a query via Mem0 semantic search."""
    mem0 = _get_mem0(request)
    if mem0 is None:
        log.warning("Context request while Mem0 is not initialized")
        return ContextResponse(context="", total_tokens=0)

    try:
        results = mem0.search(
            query=body.query,
            user_id="nova",
            limit=body.max_results,
        )

        # Mem0 v1+ returns {"results": [...]} where each item has a "memory" key
        items = results.get("results", []) if isinstance(results, dict) else results
        memory_ids = []
        lines = []
        for item in items:
            memory_text = item.get("memory", "")
            memory_id = item.get("id", "")
            if memory_text:
                lines.append(f"- {memory_text}")
            if memory_id:
                memory_ids.append(str(memory_id))

        context_text = "\n".join(lines) if lines else ""
        # Rough token estimate: ~4 chars per token
        token_estimate = len(context_text) // 4

        return ContextResponse(
            context=context_text,
            total_tokens=token_estimate,
            engram_ids=memory_ids,
            metadata={"provider": "mem0", "result_count": len(items)},
        )
    except Exception:
        log.exception("Mem0 search failed for query: %s", body.query[:100])
        return ContextResponse(context="", total_tokens=0)


@memory_router.post("/ingest", response_model=MemoryIngestResponse)
async def ingest(body: MemoryIngestRequest, request: Request):
    """Store new information via Mem0's add() — Mem0 handles extraction internally."""
    mem0 = _get_mem0(request)
    if mem0 is None:
        log.warning("Ingest request while Mem0 is not initialized")
        return MemoryIngestResponse(items_created=0, items_updated=0)

    try:
        metadata = dict(body.metadata) if body.metadata else {}
        metadata["source_type"] = body.source_type
        if body.source_id:
            metadata["source_id"] = body.source_id

        result = mem0.add(
            body.raw_text,
            user_id="nova",
            metadata=metadata,
        )

        # Mem0 add() returns {"results": [...]} with created/updated items
        items = result.get("results", []) if isinstance(result, dict) else []
        created = sum(1 for i in items if i.get("event") == "ADD")
        updated = sum(1 for i in items if i.get("event") == "UPDATE")
        item_ids = [str(i.get("id", uuid.uuid4())) for i in items]

        return MemoryIngestResponse(
            items_created=created,
            items_updated=updated,
            item_ids=item_ids,
        )
    except Exception:
        log.exception("Mem0 add failed for text: %s", body.raw_text[:100])
        return MemoryIngestResponse(items_created=0, items_updated=0)


@memory_router.post("/mark-used")
async def mark_used(body: MarkUsedRequest):
    """Feedback endpoint — Mem0 has no native feedback mechanism, so this is a no-op."""
    log.debug(
        "mark-used (no-op for Mem0): retrieval_log_id=%s, used_ids=%s",
        body.retrieval_log_id,
        body.used_ids,
    )
    return {"status": "ok", "detail": "Mem0 does not support usage feedback"}


@memory_router.get("/stats", response_model=ProviderStats)
async def stats(request: Request):
    """Return provider stats — total item count from Mem0's get_all."""
    mem0 = _get_mem0(request)
    total = 0
    last_ingestion = None

    if mem0 is not None:
        try:
            all_memories = mem0.get_all(user_id="nova")
            items = all_memories.get("results", []) if isinstance(all_memories, dict) else all_memories
            total = len(items)

            # Find most recent memory timestamp if available
            for item in items:
                ts = item.get("updated_at") or item.get("created_at")
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
                        if last_ingestion is None or dt > last_ingestion:
                            last_ingestion = dt
                    except (ValueError, TypeError):
                        pass
        except Exception:
            log.exception("Failed to retrieve Mem0 stats")

    return ProviderStats(
        provider_name="mem0",
        provider_version="0.1.0",
        total_items=total,
        last_ingestion=last_ingestion,
        capabilities=[],
    )
