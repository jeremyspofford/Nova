"""
Memory service business logic — shared by router and background tasks.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.embedding import get_embedding
from app.retrieval import to_pg_vector

log = logging.getLogger(__name__)


async def save_fact_internal(
    session: AsyncSession,
    agent_id: str,
    project_id: str,
    category: str,
    key: str,
    content: str,
    base_confidence: float,
    metadata: dict,
) -> dict:
    """Upsert a semantic fact. Used by /facts endpoint and compaction pipeline."""
    embedding = await get_embedding(content, session)
    embedding_str = to_pg_vector(embedding)
    result = await session.execute(
        text("""
            INSERT INTO semantic_memories
                (agent_id, project_id, category, key, content, embedding, embedding_model, base_confidence, metadata)
            VALUES
                (:agent_id, :project_id, :category, :key, :content, CAST(:embedding AS halfvec), :embedding_model, :base_confidence, CAST(:metadata AS jsonb))
            ON CONFLICT (project_id, category, key) DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                embedding_model = EXCLUDED.embedding_model,
                base_confidence = EXCLUDED.base_confidence,
                updated_at = now(),
                version = semantic_memories.version + 1
            RETURNING id, version, created_at, updated_at, (xmax = 0) AS is_new
        """),
        {
            "agent_id": agent_id,
            "project_id": project_id,
            "category": category,
            "key": key,
            "content": content,
            "embedding": embedding_str,
            "embedding_model": settings.embedding_model,
            "base_confidence": base_confidence,
            "metadata": json.dumps(metadata) if isinstance(metadata, dict) else metadata,
        },
    )
    row = result.fetchone()
    return {
        "id": row.id,
        "version": row.version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "is_new": row.is_new,
    }
