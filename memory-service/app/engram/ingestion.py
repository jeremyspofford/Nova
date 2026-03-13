"""
Engram ingestion worker — consumes raw events from Redis queue, decomposes
them into engrams, resolves entities, creates edges, and stores everything.

Runs as an asyncio background task via BRPOP on the engram:ingestion:queue.
Zero impact on chat latency — all processing is async background work.
"""
from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from sqlalchemy import text

from app.config import settings
from app.db.database import AsyncSessionLocal
from app.embedding import get_embedding, get_redis
from app.embedding import to_pg_vector

from .cortex_stimulus import emit_to_cortex
from .decomposition import decompose
from .entity_resolution import (
    find_contradiction_candidates,
    find_existing_entity,
    find_similar_engram,
    update_existing_engram,
)

log = logging.getLogger(__name__)

# Default tenant for single-instance Nova
DEFAULT_TENANT = "00000000-0000-0000-0000-000000000001"


async def ingestion_loop() -> None:
    """Main ingestion loop — BRPOP from Redis queue, process each event."""
    if not settings.engram_ingestion_enabled:
        log.info("Engram ingestion disabled")
        return

    log.info("Engram ingestion worker started (queue=%s)", settings.engram_ingestion_queue)

    while True:
        try:
            redis = get_redis()
            # BRPOP blocks until an item is available or timeout
            result = await redis.brpop(
                settings.engram_ingestion_queue,
                timeout=int(settings.engram_ingestion_batch_timeout),
            )
            if result is None:
                # Timeout — no items in queue, loop and retry
                continue

            _queue_name, raw_payload = result
            # Redis may return bytes or str depending on decode_responses setting
            if isinstance(raw_payload, bytes):
                raw_payload = raw_payload.decode("utf-8")

            await _process_event(raw_payload)

        except asyncio.CancelledError:
            log.info("Engram ingestion worker shutting down")
            break
        except Exception:
            log.exception("Engram ingestion error — will retry")
            await asyncio.sleep(1.0)


async def ingest_direct(
    raw_text: str,
    source_type: str = "chat",
    source_id: str | None = None,
    session_id: str | None = None,
    occurred_at: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Direct ingestion (bypasses queue). Used by the /engrams/ingest endpoint.

    Returns summary: {engrams_created, engrams_updated, edges_created, engram_ids}.
    """
    event = {
        "raw_text": raw_text,
        "source_type": source_type,
        "source_id": source_id,
        "session_id": session_id,
        "occurred_at": occurred_at,
        "metadata": metadata or {},
    }
    return await _process_event(json.dumps(event))


async def _process_event(raw_payload: str) -> dict:
    """Process a single ingestion event: decompose → resolve → store → link."""
    event = json.loads(raw_payload)
    raw_text = event.get("raw_text", "")
    source_type = event.get("source_type", "chat")
    source_id = event.get("source_id")
    occurred_at = event.get("occurred_at")
    metadata = event.get("metadata", {})

    if not raw_text.strip():
        return {"engrams_created": 0, "engrams_updated": 0, "edges_created": 0, "engram_ids": []}

    # Step 1: Decompose raw text into structured engrams
    decomposition = await decompose(raw_text)

    if not decomposition.engrams:
        log.debug("Decomposition produced no engrams for: %s", raw_text[:100])
        return {"engrams_created": 0, "engrams_updated": 0, "edges_created": 0, "engram_ids": []}

    engrams_created = 0
    engrams_updated = 0
    edges_created = 0
    engram_ids: list[UUID] = []
    # Maps decomposition index → actual engram UUID (for edge creation)
    index_to_id: dict[int, UUID] = {}

    async with AsyncSessionLocal() as session:
        # Step 2: For each decomposed engram, resolve entities and store
        for i, decomposed in enumerate(decomposition.engrams):
            try:
                engram_id, was_new = await _store_or_update_engram(
                    session=session,
                    decomposed_type=decomposed.type.value if hasattr(decomposed.type, 'value') else decomposed.type,
                    content=decomposed.content,
                    importance=decomposed.importance,
                    entities_referenced=decomposed.entities_referenced,
                    temporal=decomposed.temporal,
                    source_type=source_type,
                    source_id=source_id,
                    occurred_at=occurred_at,
                    metadata=metadata,
                )
                index_to_id[i] = engram_id
                engram_ids.append(engram_id)
                if was_new:
                    engrams_created += 1
                else:
                    engrams_updated += 1
            except Exception:
                log.exception("Failed to store engram %d: %s", i, decomposed.content[:80])

        # Step 3: Create edges from decomposition relationships
        for rel in decomposition.relationships:
            try:
                src_id = index_to_id.get(rel.from_index)
                tgt_id = index_to_id.get(rel.to_index)
                if src_id and tgt_id and src_id != tgt_id:
                    created = await _create_edge(
                        session, src_id, tgt_id,
                        rel.relation.value if hasattr(rel.relation, 'value') else rel.relation,
                        rel.strength,
                    )
                    if created:
                        edges_created += 1
            except Exception:
                log.warning("Failed to create relationship edge", exc_info=True)

        # Step 4: Create co-occurrence edges (all engrams from same input are related)
        all_ids = list(index_to_id.values())
        for j in range(len(all_ids)):
            for k in range(j + 1, len(all_ids)):
                if all_ids[j] != all_ids[k]:
                    try:
                        created = await _create_edge(
                            session, all_ids[j], all_ids[k],
                            "related_to", 0.3,  # co-occurrence edges are weaker
                        )
                        if created:
                            edges_created += 1
                    except Exception:
                        pass  # co-occurrence edges are best-effort

        # Step 5: Handle contradictions
        for contradiction in decomposition.contradictions:
            try:
                new_id = index_to_id.get(contradiction.new_index)
                if not new_id:
                    continue

                # Get embedding for the new engram to find contradiction candidates
                new_engram_content = decomposition.engrams[contradiction.new_index].content
                embedding = await get_embedding(new_engram_content, session)
                candidates = await find_contradiction_candidates(
                    session, embedding, contradiction.existing_content_hint,
                )
                for candidate in candidates:
                    created = await _create_edge(
                        session, new_id, candidate["id"],
                        "contradicts", 0.8,
                    )
                    if created:
                        edges_created += 1
                        log.info(
                            "Contradiction edge: '%s' contradicts '%s'",
                            new_engram_content[:60], candidate["content"][:60],
                        )
                        await emit_to_cortex("engram.contradiction", {
                            "engram_id": str(new_id),
                            "conflicting_with": str(candidate["id"]),
                        })
            except Exception:
                log.warning("Failed to process contradiction", exc_info=True)

        await session.commit()

    summary = {
        "engrams_created": engrams_created,
        "engrams_updated": engrams_updated,
        "edges_created": edges_created,
        "engram_ids": engram_ids,
    }
    log.info(
        "Ingested: %d created, %d updated, %d edges from: %s",
        engrams_created, engrams_updated, edges_created, raw_text[:80],
    )
    return summary


async def _store_or_update_engram(
    session,
    decomposed_type: str,
    content: str,
    importance: float,
    entities_referenced: list[str],
    temporal: dict,
    source_type: str,
    source_id: str | None,
    occurred_at: str | None,
    metadata: dict,
) -> tuple[UUID, bool]:
    """Store a new engram or update an existing one after entity resolution.

    Returns (engram_id, is_new).
    """
    # Entity resolution: check for existing matches
    existing = None

    if decomposed_type == "entity" and content:
        # Strategy 1: exact name match for entities
        existing = await find_existing_entity(session, content)

    if not existing:
        # Strategy 2: embedding similarity for same-type engrams
        embedding = await get_embedding(content, session)
        existing = await find_similar_engram(session, embedding, decomposed_type)
    else:
        embedding = await get_embedding(content, session)

    if existing:
        # Update existing engram instead of creating duplicate
        await update_existing_engram(
            session, existing["id"],
            importance_boost=max(0, importance - existing["importance"]) * 0.5,
        )
        return existing["id"], False

    # Create new engram
    fragments = {
        "entities_referenced": entities_referenced,
        **({"temporal": temporal} if temporal else {}),
    }

    # Validate source_id as UUID — set to None if not valid
    valid_source_id = None
    if source_id:
        try:
            UUID(source_id)
            valid_source_id = source_id
        except (ValueError, AttributeError):
            pass

    result = await session.execute(
        text("""
            INSERT INTO engrams (
                type, content, fragments, embedding, embedding_model,
                occurred_at, importance, source_type, source_id,
                confidence, tenant_id
            ) VALUES (
                :type, :content, CAST(:fragments AS jsonb),
                CAST(:embedding AS halfvec), :embedding_model,
                CAST(:occurred_at AS timestamptz), :importance,
                :source_type, CAST(:source_id AS uuid),
                :confidence, CAST(:tenant_id AS uuid)
            )
            RETURNING id
        """),
        {
            "type": decomposed_type,
            "content": content,
            "fragments": json.dumps(fragments),
            "embedding": to_pg_vector(embedding),
            "embedding_model": settings.embedding_model,
            "occurred_at": occurred_at,
            "importance": importance,
            "source_type": source_type,
            "source_id": valid_source_id,
            "confidence": 0.8,
            "tenant_id": DEFAULT_TENANT,
        },
    )
    row = result.fetchone()

    # Create edges from this engram to existing entities it references
    for entity_name in entities_referenced:
        try:
            entity_match = await find_existing_entity(session, entity_name)
            if entity_match and entity_match["id"] != row.id:
                await _create_edge(session, row.id, entity_match["id"], "related_to", 0.5)
        except Exception:
            pass  # entity linking is best-effort

    return row.id, True


async def _create_edge(
    session,
    source_id: UUID,
    target_id: UUID,
    relation: str,
    weight: float,
) -> bool:
    """Create or strengthen an edge between two engrams.

    Uses ON CONFLICT to increment co_activations and update weight
    if the edge already exists. Returns True if a new edge was created.
    """
    result = await session.execute(
        text("""
            INSERT INTO engram_edges (source_id, target_id, relation, weight)
            VALUES (CAST(:src AS uuid), CAST(:tgt AS uuid), :relation, :weight)
            ON CONFLICT (source_id, target_id, relation) DO UPDATE SET
                co_activations = engram_edges.co_activations + 1,
                weight = LEAST(1.0, engram_edges.weight + 0.05),
                last_co_activated = NOW()
            RETURNING (xmax = 0) AS is_new
        """),
        {
            "src": str(source_id),
            "tgt": str(target_id),
            "relation": relation,
            "weight": weight,
        },
    )
    row = result.fetchone()
    return row.is_new if row else False
