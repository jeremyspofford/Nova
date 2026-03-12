"""
Engram Network API router — Phases 1-7.

Phase 1: POST /ingest, GET /stats
Phase 2: POST /activate, POST /reconstruct
Phase 3: POST /context, GET /self-model, POST /self-model/bootstrap
Phase 4: POST /consolidate, GET /consolidation-log
Phase 5: GET /router-status, POST /mark-used
Phase 6: GET /graph
Phase 7: POST /outcome-feedback
"""
from __future__ import annotations

import logging
from collections import deque

from fastapi import APIRouter, Body, Query
from sqlalchemy import text

from nova_contracts.engram import (
    IngestRequest,
    IngestResponse,
)

from app.db.database import get_db

from .activation import spreading_activation
from .consolidation import bootstrap_self_model, run_consolidation
from .ingestion import ingest_direct
from .outcome_feedback import process_feedback
from .reconstruction import get_self_model_summary, reconstruct
from .neural_router.serve import get_cached_model
from .retrieval_logger import get_labeled_observation_count, get_observation_count, mark_engrams_used
from .working_memory import assemble_context, format_context_prompt

log = logging.getLogger(__name__)

engram_router = APIRouter(prefix="/api/v1/engrams", tags=["engrams"])


# ── Phase 1: Ingestion ────────────────────────────────────────────────


@engram_router.post("/ingest", response_model=IngestResponse, status_code=201)
async def ingest_engram(req: IngestRequest):
    """Ingest raw text directly into the engram graph (bypasses queue)."""
    result = await ingest_direct(
        raw_text=req.raw_text,
        source_type=req.source_type.value if hasattr(req.source_type, "value") else req.source_type,
        source_id=str(req.source_id) if req.source_id else None,
        session_id=str(req.session_id) if req.session_id else None,
        occurred_at=req.occurred_at.isoformat() if req.occurred_at else None,
        metadata=req.metadata,
    )
    return IngestResponse(
        engrams_created=result["engrams_created"],
        engrams_updated=result["engrams_updated"],
        edges_created=result["edges_created"],
        engram_ids=result["engram_ids"],
    )


@engram_router.get("/stats")
async def engram_stats():
    """Return statistics about the engram graph."""
    async with get_db() as session:
        type_rows = await session.execute(
            text("""
                SELECT type, count(*) AS cnt,
                       count(*) FILTER (WHERE superseded) AS superseded_cnt
                FROM engrams
                GROUP BY type ORDER BY cnt DESC
            """)
        )
        by_type = {row.type: {"total": row.cnt, "superseded": row.superseded_cnt} for row in type_rows}

        edge_rows = await session.execute(
            text("""
                SELECT relation, count(*) AS cnt,
                       round(avg(weight)::numeric, 3) AS avg_weight
                FROM engram_edges
                GROUP BY relation ORDER BY cnt DESC
            """)
        )
        by_relation = {
            row.relation: {"count": row.cnt, "avg_weight": float(row.avg_weight)}
            for row in edge_rows
        }

        total_engrams = (await session.execute(text("SELECT count(*) FROM engrams"))).scalar()
        total_edges = (await session.execute(text("SELECT count(*) FROM engram_edges"))).scalar()
        total_archived = (await session.execute(text("SELECT count(*) FROM engram_archive"))).scalar()

    return {
        "total_engrams": total_engrams,
        "total_edges": total_edges,
        "total_archived": total_archived,
        "by_type": by_type,
        "by_relation": by_relation,
    }


# ── Phase 2: Spreading Activation + Reconstruction ────────────────────


@engram_router.post("/activate")
async def activate_engrams(
    query: str,
    seed_count: int | None = None,
    max_hops: int | None = None,
    max_results: int | None = None,
):
    """Run spreading activation on a query and return activated engrams."""
    async with get_db() as session:
        activated = await spreading_activation(
            session, query,
            seed_count=seed_count,
            max_hops=max_hops,
            max_results=max_results,
        )
    return {
        "count": len(activated),
        "engrams": [
            {
                "id": a.id,
                "type": a.type,
                "content": a.content,
                "activation": round(a.activation, 4),
                "importance": round(a.importance, 4),
                "final_score": round(a.final_score, 4),
                "convergence_paths": a.convergence_paths,
                "source_type": a.source_type,
            }
            for a in activated
        ],
    }


@engram_router.post("/reconstruct")
async def reconstruct_memory(query: str):
    """Activate + reconstruct coherent memory text from the engram graph."""
    async with get_db() as session:
        activated = await spreading_activation(session, query)
        if not activated:
            return {"text": "", "engram_count": 0}

        self_model = await get_self_model_summary(session)
        text_result = await reconstruct(
            session, activated,
            context=query,
            self_model_summary=self_model,
        )
    return {
        "text": text_result,
        "engram_count": len(activated),
        "top_engrams": [
            {"id": a.id, "type": a.type, "score": round(a.final_score, 4)}
            for a in activated[:5]
        ],
    }


# ── Phase 3: Working Memory Gate ───────────────────────────────────────


@engram_router.post("/context")
async def get_engram_context(
    query: str = Body(...),
    session_id: str = Body(""),
    current_turn: int = Body(0),
):
    """Assemble the full working memory context for a query.

    This is the main endpoint the orchestrator calls to get engram-powered
    memory context for prompt assembly.
    """
    async with get_db() as session:
        ctx = await assemble_context(
            session,
            query=query,
            session_id=session_id,
            current_turn=current_turn,
        )
    prompt = format_context_prompt(ctx)
    return {
        "context": prompt,
        "total_tokens": ctx.total_tokens,
        "sections": {
            "self_model": bool(ctx.self_model),
            "active_goal": bool(ctx.active_goal),
            "memories": bool(ctx.memories),
            "key_decisions": bool(ctx.key_decisions),
            "open_threads": bool(ctx.open_threads),
        },
        "engram_ids": ctx.engram_ids,
        "retrieval_log_id": ctx.retrieval_log_id,
    }


@engram_router.get("/self-model")
async def get_self_model():
    """Return the current self-model summary."""
    async with get_db() as session:
        summary = await get_self_model_summary(session)
    return {"self_model": summary}


@engram_router.post("/self-model/bootstrap")
async def bootstrap_self_model_endpoint():
    """Seed default self-model engrams (idempotent — skips if already present)."""
    async with get_db() as session:
        created = await bootstrap_self_model(session)
        await session.commit()
    return {"created": created}


# ── Phase 4: Consolidation ─────────────────────────────────────────────


@engram_router.post("/consolidate")
async def trigger_consolidation():
    """Manually trigger a consolidation cycle."""
    stats = await run_consolidation(trigger="manual")
    return stats


@engram_router.get("/consolidation-log")
async def get_consolidation_log(limit: int = Query(default=20, le=100)):
    """Return recent consolidation log entries."""
    async with get_db() as session:
        result = await session.execute(
            text("""
                SELECT id, trigger_type, engrams_reviewed, schemas_created,
                       edges_strengthened, edges_pruned, engrams_pruned,
                       engrams_merged, contradictions_resolved,
                       self_model_updates::text, model_used, duration_ms,
                       created_at
                FROM consolidation_log
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        )
        rows = result.fetchall()

    import json
    return {
        "count": len(rows),
        "entries": [
            {
                "id": str(row.id),
                "trigger": row.trigger_type,
                "engrams_reviewed": row.engrams_reviewed,
                "schemas_created": row.schemas_created,
                "edges_strengthened": row.edges_strengthened,
                "edges_pruned": row.edges_pruned,
                "engrams_pruned": row.engrams_pruned,
                "engrams_merged": row.engrams_merged,
                "contradictions_resolved": row.contradictions_resolved,
                "self_model_updates": json.loads(row.self_model_updates) if row.self_model_updates else {},
                "model_used": row.model_used,
                "duration_ms": row.duration_ms,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


# ── Phase 5: Neural Router Status & Mark-Used ─────────────────────────


@engram_router.get("/router-status")
async def router_status():
    """Neural Router status: mode, model info, observation counts."""
    async with get_db() as session:
        obs_count = await get_observation_count(session)
        labeled_count = await get_labeled_observation_count(session)

    model, arch = get_cached_model()

    if model is not None:
        mode = "embedding_reranker" if arch == "embedding" else "scalar_reranker"
    elif obs_count >= 200:
        mode = "ready_for_training"
    else:
        mode = "cosine_only"

    return {
        "observation_count": obs_count,
        "labeled_count": labeled_count,
        "mode": mode,
        "model_loaded": model is not None,
        "architecture": arch,
        "ready_for_training": labeled_count >= 200,
        "message": (
            f"Active: {mode} ({obs_count} observations, {labeled_count} labeled)"
            if model is not None
            else f"Collecting observations: {labeled_count}/200 labeled"
        ),
    }


@engram_router.post("/mark-used")
async def mark_used(
    retrieval_log_id: str = Body(...),
    engram_ids_used: list[str] = Body(...),
):
    """Mark which engrams were actually used from a retrieval context.

    Called by the orchestrator after the LLM response to provide ground
    truth for Neural Router training.
    """
    async with get_db() as session:
        await mark_engrams_used(session, retrieval_log_id, engram_ids_used)
        await session.commit()
    return {"status": "ok"}


# ── Phase 6: Graph Visualization ───────────────────────────────────────


@engram_router.get("/graph")
async def get_graph(
    center_id: str | None = Query(default=None, description="Engram ID to center on"),
    query: str | None = Query(default=None, description="Query to find center via activation"),
    depth: int = Query(default=2, ge=1, le=4, description="BFS depth"),
    max_nodes: int = Query(default=50, ge=10, le=200),
):
    """Return a subgraph for visualization (nodes + edges).

    Provide either center_id or query. If query is given, the top activated
    engram becomes the center. Returns a D3-compatible node/link structure.
    """
    async with get_db() as session:
        # Determine center node
        if query and not center_id:
            activated = await spreading_activation(session, query, max_results=1)
            if activated:
                center_id = activated[0].id

        if not center_id:
            # Fall back to most-accessed engram
            row = await session.execute(
                text("""
                    SELECT id::text FROM engrams
                    WHERE NOT superseded
                    ORDER BY access_count DESC, activation DESC
                    LIMIT 1
                """)
            )
            r = row.fetchone()
            if not r:
                return {"nodes": [], "edges": []}
            center_id = r.id

        # BFS from center
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(center_id, 0)])
        node_ids: list[str] = []

        while queue and len(node_ids) < max_nodes:
            current_id, current_depth = queue.popleft()
            if current_id in visited:
                continue
            visited.add(current_id)
            node_ids.append(current_id)

            if current_depth < depth:
                neighbors = await session.execute(
                    text("""
                        SELECT target_id::text AS neighbor_id FROM engram_edges
                        WHERE source_id = CAST(:id AS uuid)
                        UNION
                        SELECT source_id::text AS neighbor_id FROM engram_edges
                        WHERE target_id = CAST(:id AS uuid)
                    """),
                    {"id": current_id},
                )
                for row in neighbors:
                    if row.neighbor_id not in visited:
                        queue.append((row.neighbor_id, current_depth + 1))

        if not node_ids:
            return {"nodes": [], "edges": []}

        # Fetch node details
        nodes_result = await session.execute(
            text("""
                SELECT id::text, type, content, activation, importance,
                       access_count, confidence, source_type,
                       superseded, created_at
                FROM engrams
                WHERE id = ANY(CAST(:ids AS uuid[]))
            """),
            {"ids": node_ids},
        )

        nodes = [
            {
                "id": row.id,
                "type": row.type,
                "content": row.content[:200],
                "activation": round(float(row.activation), 3),
                "importance": round(float(row.importance), 3),
                "access_count": row.access_count,
                "confidence": round(float(row.confidence), 3),
                "source_type": row.source_type,
                "superseded": row.superseded,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in nodes_result
        ]

        # Fetch edges between these nodes
        edges_result = await session.execute(
            text("""
                SELECT source_id::text, target_id::text, relation,
                       weight, co_activations
                FROM engram_edges
                WHERE source_id = ANY(CAST(:ids AS uuid[]))
                  AND target_id = ANY(CAST(:ids AS uuid[]))
            """),
            {"ids": node_ids},
        )

        edges = [
            {
                "source": row.source_id,
                "target": row.target_id,
                "relation": row.relation,
                "weight": round(float(row.weight), 3),
                "co_activations": row.co_activations,
            }
            for row in edges_result
        ]

    return {
        "center_id": center_id,
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


# ── Phase 7: Outcome Feedback ───────────────────────────────────────────


from pydantic import BaseModel as _BaseModel


class OutcomeFeedbackEntry(_BaseModel):
    engram_id: str
    outcome_score: float
    task_type: str = "unknown"


@engram_router.post("/outcome-feedback")
async def receive_outcome_feedback(feedback: list[OutcomeFeedbackEntry]):
    """Receive outcome scores and adjust engram activation/importance/edges."""
    async with get_db() as session:
        stats = await process_feedback(session, [e.model_dump() for e in feedback])
    return {"status": "ok", **stats}
