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


@dataclass
class RawResult:
    id: str
    content: str
    metadata: dict
    created_at: object
    rank: int
    source: str  # "vector" or "keyword"


@dataclass
class FusedResult:
    id: str
    content: str
    metadata: dict
    created_at: object
    score: float
    vector_rank: int | None = None
    keyword_rank: int | None = None


async def hybrid_search(
    session: AsyncSession,
    agent_id: str,
    query_embedding: list[float],
    query_text: str,
    tiers: list[str],
    limit: int,
    vector_weight: float,
    keyword_weight: float,
) -> list[FusedResult]:
    """
    Execute hybrid vector + keyword search across multiple memory tiers,
    fuse results using RRF, and return ranked results.
    """
    all_raw: list[RawResult] = []

    for tier in tiers:
        table = TIER_TABLES.get(tier)
        if not table:
            log.warning("Unknown memory tier: %s", tier)
            continue

        # Fetch more than limit from each source so RRF has candidates to merge
        fetch_limit = min(limit * 3, 100)

        vector_results = await _vector_search(session, table, agent_id, query_embedding, fetch_limit)
        keyword_results = await _keyword_search(session, table, agent_id, query_text, fetch_limit)

        all_raw.extend(vector_results)
        all_raw.extend(keyword_results)

    return _reciprocal_rank_fusion(all_raw, limit, vector_weight, keyword_weight)


async def _vector_search(
    session: AsyncSession,
    table: str,
    agent_id: str,
    embedding: list[float],
    limit: int,
) -> list[RawResult]:
    """HNSW approximate nearest neighbor search using cosine distance."""
    if not embedding:
        return []

    # halfvec cosine distance operator: <=>
    sql = text(f"""
        SELECT id::text, content, metadata, created_at,
               row_number() OVER (ORDER BY embedding <=> :embedding) AS rank
        FROM {table}
        WHERE agent_id = :agent_id
          AND embedding IS NOT NULL
        ORDER BY embedding <=> :embedding
        LIMIT :limit
    """)  # noqa: S608 — table name comes from our TIER_TABLES dict, not user input

    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
    rows = await session.execute(sql, {"embedding": embedding_str, "agent_id": agent_id, "limit": limit})

    return [
        RawResult(
            id=str(row.id),
            content=row.content,
            metadata=dict(row.metadata),
            created_at=row.created_at,
            rank=row.rank,
            source="vector",
        )
        for row in rows
    ]


async def _keyword_search(
    session: AsyncSession,
    table: str,
    agent_id: str,
    query: str,
    limit: int,
) -> list[RawResult]:
    """Full-text search using PostgreSQL tsvector/GIN with ts_rank scoring."""
    sql = text(f"""
        SELECT id::text, content, metadata, created_at,
               row_number() OVER (ORDER BY ts_rank(tsv, query) DESC) AS rank
        FROM {table},
             plainto_tsquery('english', :query) AS query
        WHERE agent_id = :agent_id
          AND tsv @@ query
        ORDER BY ts_rank(tsv, query) DESC
        LIMIT :limit
    """)  # noqa: S608

    rows = await session.execute(sql, {"query": query, "agent_id": agent_id, "limit": limit})

    return [
        RawResult(
            id=str(row.id),
            content=row.content,
            metadata=dict(row.metadata),
            created_at=row.created_at,
            rank=row.rank,
            source="keyword",
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

    return [
        FusedResult(
            id=doc_id,
            content=result_data[doc_id].content,
            metadata=result_data[doc_id].metadata,
            created_at=result_data[doc_id].created_at,
            score=scores[doc_id],
            vector_rank=vector_ranks.get(doc_id),
            keyword_rank=keyword_ranks.get(doc_id),
        )
        for doc_id in sorted_ids[:limit]
    ]
