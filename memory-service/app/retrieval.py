"""
Hybrid retrieval engine using Reciprocal Rank Fusion (RRF).

Architecture: vector search (pgvector HNSW) + keyword search (tsvector GIN)
merged via RRF: score(doc) = Σ weight_i / (k + rank_i(doc))

See Part 3 of the architecture doc for full justification.
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

# RRF smoothing constant — k=60 is the standard value from the original paper
RRF_K = 60

# Table name mapping per memory tier
TIER_TABLES = {
    "working": "working_memories",
    "episodic": "episodic_memories",
    "semantic": "semantic_memories",
    "procedural": "procedural_memories",
}


def tier_table(tier) -> str:
    """Resolve tier (string or MemoryTier enum) to table name."""
    key = tier.value if hasattr(tier, 'value') else tier
    table = TIER_TABLES.get(key)
    if not table:
        raise ValueError(f"Unknown memory tier: {tier}")
    return table


def to_pg_vector(embedding: list[float]) -> str:
    """Serialize embedding list to PostgreSQL halfvec string literal."""
    return "[" + ",".join(str(v) for v in embedding) + "]"


@dataclass
class RawResult:
    id: str
    content: str
    metadata: dict
    created_at: object
    rank: int
    source: str   # "vector" or "keyword"
    tier: str = ""  # memory tier name
    base_confidence: float = 1.0
    last_accessed_at: object = None


@dataclass
class FusedResult:
    id: str
    content: str
    metadata: dict
    created_at: object
    score: float
    tier: str = ""
    vector_rank: int | None = None
    keyword_rank: int | None = None
    effective_confidence: float = 1.0


def _actr_confidence(base_confidence: float, last_accessed_at) -> float:
    """ACT-R power-law decay: confidence * days^(-0.5), floored at 0.05."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if last_accessed_at is None:
        return base_confidence
    if hasattr(last_accessed_at, 'tzinfo') and last_accessed_at.tzinfo is None:
        last_accessed_at = last_accessed_at.replace(tzinfo=timezone.utc)
    from app.config import SECONDS_PER_DAY
    days = max((now - last_accessed_at).total_seconds() / SECONDS_PER_DAY, 1 / SECONDS_PER_DAY)
    return max(base_confidence * days ** -0.5, 0.05)


async def hybrid_search(
    session: AsyncSession,
    agent_id: str,
    query_embedding: list[float],
    query_text: str,
    tiers: list[str],
    limit: int,
    vector_weight: float,
    keyword_weight: float,
    metadata_filter: dict | None = None,
) -> list[FusedResult]:
    """
    Execute hybrid vector + keyword search across multiple memory tiers,
    fuse results using RRF, and return ranked results.

    metadata_filter: optional dict of key/value pairs that must match in the
    JSONB metadata column (top-level equality via @> containment).
    """
    all_raw: list[RawResult] = []

    # Fire all vector + keyword searches in parallel across all tiers
    import asyncio
    coros = []
    for tier in tiers:
        table = TIER_TABLES.get(tier)
        if not table:
            log.warning("Unknown memory tier: %s", tier)
            continue
        fetch_limit = min(limit * 3, 100)
        coros.append(_vector_search(session, table, agent_id, query_embedding, fetch_limit, tier, metadata_filter))
        coros.append(_keyword_search(session, table, agent_id, query_text, fetch_limit, tier, metadata_filter))

    if coros:
        results = await asyncio.gather(*coros)
        for result_list in results:
            all_raw.extend(result_list)

    fused = _reciprocal_rank_fusion(all_raw, limit, vector_weight, keyword_weight)

    # Touch last_accessed_at for retrieved semantic memories
    semantic_ids = [r.id for r in fused if r.tier == "semantic"]
    if semantic_ids:
        await _touch_last_accessed(session, semantic_ids)

    return fused


async def _vector_search(
    session: AsyncSession,
    table: str,
    agent_id: str,
    embedding: list[float],
    limit: int,
    tier: str = "",
    metadata_filter: dict | None = None,
) -> list[RawResult]:
    """HNSW approximate nearest neighbor search using cosine distance."""
    if not embedding:
        return []

    extra_cols = ", base_confidence, last_accessed_at" if table == "semantic_memories" else ""
    meta_clause = " AND metadata @> CAST(:meta_filter AS jsonb)" if metadata_filter else ""
    sql = text(f"""
        SELECT id::text, content, metadata, created_at{extra_cols},
               row_number() OVER (ORDER BY embedding <=> :embedding) AS rank
        FROM {table}
        WHERE agent_id = :agent_id
          AND embedding IS NOT NULL{meta_clause}
        ORDER BY embedding <=> :embedding
        LIMIT :limit
    """)  # noqa: S608 — table name comes from our TIER_TABLES dict, not user input

    params: dict = {"embedding": to_pg_vector(embedding), "agent_id": agent_id, "limit": limit}
    if metadata_filter:
        import json as _json
        params["meta_filter"] = _json.dumps(metadata_filter)
    rows = await session.execute(sql, params)

    return [
        RawResult(
            id=str(row.id),
            content=row.content,
            metadata=dict(row.metadata),
            created_at=row.created_at,
            rank=row.rank,
            source="vector",
            tier=tier,
            base_confidence=getattr(row, 'base_confidence', 1.0) or 1.0,
            last_accessed_at=getattr(row, 'last_accessed_at', None),
        )
        for row in rows
    ]


async def _keyword_search(
    session: AsyncSession,
    table: str,
    agent_id: str,
    query: str,
    limit: int,
    tier: str = "",
    metadata_filter: dict | None = None,
) -> list[RawResult]:
    """Full-text search using PostgreSQL tsvector/GIN with ts_rank scoring."""
    extra_cols = ", base_confidence, last_accessed_at" if table == "semantic_memories" else ""
    meta_clause = " AND metadata @> CAST(:meta_filter AS jsonb)" if metadata_filter else ""
    sql = text(f"""
        SELECT id::text, content, metadata, created_at{extra_cols},
               row_number() OVER (ORDER BY ts_rank(tsv, query) DESC) AS rank
        FROM {table},
             plainto_tsquery('english', :query) AS query
        WHERE agent_id = :agent_id
          AND tsv @@ query{meta_clause}
        ORDER BY ts_rank(tsv, query) DESC
        LIMIT :limit
    """)  # noqa: S608

    params: dict = {"query": query, "agent_id": agent_id, "limit": limit}
    if metadata_filter:
        import json as _json
        params["meta_filter"] = _json.dumps(metadata_filter)
    rows = await session.execute(sql, params)

    return [
        RawResult(
            id=str(row.id),
            content=row.content,
            metadata=dict(row.metadata),
            created_at=row.created_at,
            rank=row.rank,
            source="keyword",
            tier=tier,
            base_confidence=getattr(row, 'base_confidence', 1.0) or 1.0,
            last_accessed_at=getattr(row, 'last_accessed_at', None),
        )
        for row in rows
    ]


def _reciprocal_rank_fusion(
    results: list[RawResult],
    limit: int,
    vector_weight: float,
    keyword_weight: float,
) -> list[FusedResult]:
    """
    Merge vector and keyword results via RRF.
    RRF score = Σ weight_i / (k + rank_i)
    """
    scores: dict[str, float] = defaultdict(float)
    vector_ranks: dict[str, int] = {}
    keyword_ranks: dict[str, int] = {}
    result_data: dict[str, RawResult] = {}

    for r in results:
        result_data[r.id] = r

        if r.source == "vector":
            scores[r.id] += vector_weight / (RRF_K + r.rank)
            vector_ranks[r.id] = r.rank
        else:
            scores[r.id] += keyword_weight / (RRF_K + r.rank)
            keyword_ranks[r.id] = r.rank

    sorted_ids = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)

    fused = []
    for doc_id in sorted_ids[:limit]:
        raw = result_data[doc_id]
        eff_conf = _actr_confidence(raw.base_confidence, raw.last_accessed_at)
        # Weight semantic results by effective confidence
        final_score = scores[doc_id]
        if raw.tier == "semantic":
            final_score *= eff_conf
        fused.append(FusedResult(
            id=doc_id,
            content=raw.content,
            metadata=raw.metadata,
            created_at=raw.created_at,
            score=final_score,
            tier=raw.tier,
            vector_rank=vector_ranks.get(doc_id),
            keyword_rank=keyword_ranks.get(doc_id),
            effective_confidence=eff_conf,
        ))

    fused.sort(key=lambda f: f.score, reverse=True)
    return fused


async def _touch_last_accessed(session: AsyncSession, ids: list[str]) -> None:
    """Update last_accessed_at for retrieved semantic memories."""
    if not ids:
        return
    try:
        await session.execute(
            text("UPDATE semantic_memories SET last_accessed_at = now() WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": ids},
        )
    except Exception:
        log.warning("Failed to touch last_accessed_at", exc_info=True)
