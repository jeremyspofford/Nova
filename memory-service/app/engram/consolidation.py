"""
Consolidation daemon — Phase 4 of the Engram Network ("Sleep Cycle").

Transforms raw experience into lasting wisdom through six phases:
1. Replay & Review — walk through recent episodes
2. Pattern Extraction — promote recurring themes to schema engrams
3. Edge Strengthening — Hebbian learning (fire together, wire together)
4. Contradiction Resolution — resolve conflicting facts
5. Pruning & Merging — archive dead weight, merge near-duplicates
6. Self-Model Update — refresh identity from corrections and patterns

Triggers: idle (30+ min), nightly (3 AM), threshold (50+ new engrams).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.config import settings
from app.db.database import AsyncSessionLocal
from app.embedding import get_embedding
from app.embedding import to_pg_vector
from .cortex_stimulus import emit_to_cortex

log = logging.getLogger(__name__)

# Track state across consolidation cycles
_last_consolidation_at: float = 0.0
_engrams_since_last: int = 0
_consolidation_lock = asyncio.Lock()


async def consolidation_loop() -> None:
    """Background loop that triggers consolidation on idle/threshold/schedule."""
    if not settings.engram_consolidation_enabled:
        log.info("Engram consolidation disabled")
        return

    global _last_consolidation_at
    _last_consolidation_at = time.monotonic()
    log.info("Consolidation daemon started")

    while True:
        try:
            await asyncio.sleep(60)  # Check every minute

            now_mono = time.monotonic()
            idle_minutes = (now_mono - _last_consolidation_at) / 60

            # Check triggers
            trigger = None
            if idle_minutes >= settings.engram_consolidation_idle_minutes:
                trigger = "idle"
            elif _engrams_since_last >= settings.engram_consolidation_threshold:
                trigger = "threshold"
            else:
                # Check nightly schedule
                now_utc = datetime.now(timezone.utc)
                if (now_utc.hour == settings.engram_consolidation_nightly_hour
                        and idle_minutes >= 5):  # Don't run nightly if recently consolidated
                    trigger = "scheduled"

            if trigger:
                await run_consolidation(trigger)
                _last_consolidation_at = time.monotonic()

        except asyncio.CancelledError:
            log.info("Consolidation daemon shutting down")
            break
        except Exception:
            log.exception("Consolidation check error — will retry")


def notify_new_engrams(count: int = 1) -> None:
    """Called by ingestion to track new engram count for threshold trigger."""
    global _engrams_since_last
    _engrams_since_last += count


async def run_consolidation(trigger: str = "manual") -> dict:
    """Run a full consolidation cycle. Returns summary stats.

    Uses a mutex to prevent concurrent consolidation cycles from corrupting data.
    Each phase is isolated — a failure in one phase doesn't kill the cycle.
    """
    global _engrams_since_last

    if _consolidation_lock.locked():
        log.info("Consolidation already running, skipping trigger=%s", trigger)
        return {"skipped": True, "reason": "already_running"}

    async with _consolidation_lock:
        start_time = time.monotonic()
        log.info("Consolidation starting (trigger=%s)", trigger)

        stats = {
            "engrams_reviewed": 0,
            "schemas_created": 0,
            "edges_strengthened": 0,
            "edges_pruned": 0,
            "engrams_pruned": 0,
            "engrams_merged": 0,
            "contradictions_resolved": 0,
            "self_model_updates": {},
        }

        async with AsyncSessionLocal() as session:
            # Phase 1: Replay & Review — count recent engrams (expanded to 7 days)
            count_row = await session.execute(
                text("""
                    SELECT count(*) FROM engrams
                    WHERE NOT superseded
                      AND created_at > NOW() - INTERVAL '7 days'
                """)
            )
            stats["engrams_reviewed"] = count_row.scalar() or 0

            # Phase 2: Pattern Extraction → Schema engrams
            try:
                schemas_created = await _extract_patterns(session)
                stats["schemas_created"] = schemas_created
            except Exception:
                log.warning("Consolidation Phase 2 (pattern extraction) failed", exc_info=True)

            # Phase 3: Edge Strengthening & Weakening (Hebbian)
            try:
                strengthened, weakened = await _hebbian_update(session)
                stats["edges_strengthened"] = strengthened
                stats["edges_pruned"] = weakened
            except Exception:
                log.warning("Consolidation Phase 3 (Hebbian update) failed", exc_info=True)

            # Phase 4: Contradiction Resolution
            try:
                resolved = await _resolve_contradictions(session)
                stats["contradictions_resolved"] = resolved
            except Exception:
                log.warning("Consolidation Phase 4 (contradiction resolution) failed", exc_info=True)

            # Phase 5: Pruning & Merging
            try:
                pruned = await _prune_dead_engrams(session)
                merged = await _merge_duplicates(session)
                stats["engrams_pruned"] = pruned
                stats["engrams_merged"] = merged
            except Exception:
                log.warning("Consolidation Phase 5 (pruning/merging) failed", exc_info=True)

            # Phase 6: Self-Model Update
            try:
                self_updates = await _update_self_model(session)
                stats["self_model_updates"] = self_updates
            except Exception:
                log.warning("Consolidation Phase 6 (self-model update) failed", exc_info=True)

            # Log to consolidation_log BEFORE final commit (atomic with changes)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            await session.execute(
                text("""
                    INSERT INTO consolidation_log
                        (trigger_type, engrams_reviewed, schemas_created,
                         edges_strengthened, edges_pruned, engrams_pruned,
                         engrams_merged, contradictions_resolved,
                         self_model_updates, model_used, duration_ms)
                    VALUES
                        (:trigger, :reviewed, :schemas, :strengthened, :pruned_edges,
                         :pruned_engrams, :merged, :contradictions,
                         CAST(:self_updates AS jsonb), :model, :duration)
                """),
                {
                    "trigger": trigger,
                    "reviewed": stats["engrams_reviewed"],
                    "schemas": stats["schemas_created"],
                    "strengthened": stats["edges_strengthened"],
                    "pruned_edges": stats["edges_pruned"],
                    "pruned_engrams": stats["engrams_pruned"],
                    "merged": stats["engrams_merged"],
                    "contradictions": stats["contradictions_resolved"],
                    "self_updates": json.dumps(stats["self_model_updates"]),
                    "model": settings.engram_consolidation_model,
                    "duration": duration_ms,
                },
            )
            await session.commit()

        _engrams_since_last = 0
        log.info(
            "Consolidation complete (%s): %d reviewed, %d schemas, %d pruned, %d merged, %dms",
            trigger, stats["engrams_reviewed"], stats["schemas_created"],
            stats["engrams_pruned"], stats["engrams_merged"], duration_ms,
        )
        try:
            await emit_to_cortex("consolidation.complete", {
                "engrams_reviewed": stats.get("engrams_reviewed", 0),
                "schemas_created": stats.get("schemas_created", 0),
                "contradictions_resolved": stats.get("contradictions_resolved", 0),
            })
        except Exception:
            log.warning("Failed to emit consolidation stimulus to cortex", exc_info=True)
        return stats


async def _extract_patterns(session) -> int:
    """Phase 2: Find recurring themes and promote to schema engrams.

    Looks for fact/preference engrams that share entities with 3+ episodes.
    Uses LLM to synthesize the pattern into a schema engram.
    """
    # Find entities referenced by 3+ distinct engrams
    result = await session.execute(
        text("""
            SELECT e.content AS entity_name, count(DISTINCT ee.source_id) AS ref_count
            FROM engrams e
            JOIN engram_edges ee ON ee.target_id = e.id
            WHERE e.type = 'entity'
              AND NOT e.superseded
            GROUP BY e.id, e.content
            HAVING count(DISTINCT ee.source_id) >= 3
            ORDER BY ref_count DESC
            LIMIT 10
        """)
    )
    frequent_entities = result.fetchall()

    schemas_created = 0
    for entity_row in frequent_entities:
        # Check if we already have a schema for this entity
        existing = await session.execute(
            text("""
                SELECT id FROM engrams
                WHERE type = 'schema'
                  AND NOT superseded
                  AND content ILIKE :pattern
                LIMIT 1
            """),
            {"pattern": f"%{entity_row.entity_name}%"},
        )
        if existing.fetchone():
            continue

        # Gather the related engrams' content
        related = await session.execute(
            text("""
                SELECT DISTINCT e2.content, e2.type
                FROM engram_edges ee
                JOIN engrams e ON e.id = ee.target_id AND e.content = :entity
                JOIN engram_edges ee2 ON ee2.target_id = e.id
                JOIN engrams e2 ON e2.id = ee2.source_id AND NOT e2.superseded
                WHERE e2.type IN ('fact', 'preference', 'episode')
                LIMIT 10
            """),
            {"entity": entity_row.entity_name},
        )
        related_items = related.fetchall()
        if len(related_items) < 3:
            continue

        # Synthesize a schema via LLM
        items_text = "\n".join(f"- [{r.type}] {r.content}" for r in related_items)
        schema_content = await _synthesize_schema(entity_row.entity_name, items_text)
        if schema_content:
            embedding = await get_embedding(schema_content, session)
            await session.execute(
                text("""
                    INSERT INTO engrams (type, content, embedding, embedding_model,
                                        importance, source_type, confidence)
                    VALUES ('schema', :content, CAST(:embedding AS halfvec), :model,
                            0.7, 'consolidation', 0.7)
                """),
                {
                    "content": schema_content,
                    "embedding": to_pg_vector(embedding),
                    "model": settings.embedding_model,
                },
            )
            schemas_created += 1

    return schemas_created


async def _synthesize_schema(entity_name: str, items_text: str) -> str:
    """Use LLM to extract a generalized pattern from related engrams."""
    try:
        from .decomposition import resolve_model
        model = await resolve_model(settings.engram_consolidation_model)
        async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=30.0) as client:
            resp = await client.post(
                "/complete",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Extract a single generalized pattern from these observations. Return one concise sentence."},
                        {"role": "user", "content": f"Entity: {entity_name}\n\nObservations:\n{items_text}"},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 200,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", "")
            if isinstance(content, list):
                content = content[0].get("text", "") if content else ""
            return content.strip()
    except Exception:
        log.warning("Schema synthesis failed", exc_info=True)
        return ""


async def _hebbian_update(session) -> tuple[int, int]:
    """Phase 3: Strengthen co-activated edges, weaken unused ones.

    edge.weight = edge.weight × decay + co_activation_boost

    Only decays/prunes edges older than 7 days to protect young graphs from
    the death spiral where new edges get decayed and pruned every cycle.
    """
    # Strengthen: edges with recent co-activations
    result = await session.execute(
        text("""
            UPDATE engram_edges
            SET weight = LEAST(1.0, weight * :decay + 0.1 * (co_activations - 1)),
                co_activations = 1
            WHERE co_activations > 1
            RETURNING id
        """),
        {"decay": settings.engram_edge_decay},
    )
    strengthened = len(result.fetchall())

    # Weaken: decay edge weights slightly — only for edges older than 7 days
    # (protect young edges from being decayed before they get a chance to strengthen)
    result = await session.execute(
        text("""
            UPDATE engram_edges
            SET weight = GREATEST(0.01, weight * :decay)
            WHERE co_activations <= 1
              AND weight > 0.01
              AND created_at < NOW() - INTERVAL '7 days'
            RETURNING id
        """),
        {"decay": settings.engram_edge_decay},
    )
    weakened = len(result.fetchall())

    # Prune edges that have decayed to near-zero AND are old
    result = await session.execute(
        text("""
            DELETE FROM engram_edges
            WHERE weight < 0.02
              AND co_activations <= 1
              AND created_at < NOW() - INTERVAL '14 days'
            RETURNING id
        """)
    )
    pruned = len(result.fetchall())

    return strengthened, weakened + pruned


async def _resolve_contradictions(session) -> int:
    """Phase 4: Resolve contradiction edges.

    Newer wins by default, higher confidence wins on ties.
    """
    result = await session.execute(
        text("""
            SELECT ee.id AS edge_id,
                   e1.id AS source_id, e1.content AS source_content,
                   e1.confidence AS source_conf, e1.created_at AS source_created,
                   e2.id AS target_id, e2.content AS target_content,
                   e2.confidence AS target_conf, e2.created_at AS target_created
            FROM engram_edges ee
            JOIN engrams e1 ON e1.id = ee.source_id
            JOIN engrams e2 ON e2.id = ee.target_id
            WHERE ee.relation = 'contradicts'
              AND NOT e1.superseded
              AND NOT e2.superseded
        """)
    )
    contradictions = result.fetchall()
    resolved = 0

    for c in contradictions:
        # Determine winner
        loser_id = None
        conf_delta = abs(c.source_conf - c.target_conf)

        if conf_delta > 0.3:
            # Confidence winner
            loser_id = c.target_id if c.source_conf > c.target_conf else c.source_id
        else:
            # Temporal winner (newer wins)
            loser_id = c.source_id if c.target_created > c.source_created else c.target_id

        if loser_id:
            await session.execute(
                text("""
                    UPDATE engrams
                    SET superseded = TRUE, activation = 0.01, updated_at = NOW()
                    WHERE id = CAST(:id AS uuid)
                """),
                {"id": str(loser_id)},
            )
            resolved += 1

    return resolved


async def _prune_dead_engrams(session) -> int:
    """Phase 5a: Move dead engrams to archive.

    Dead = activation < floor AND no strong edges AND never accessed.
    """
    result = await session.execute(
        text("""
            WITH dead AS (
                SELECT e.id
                FROM engrams e
                WHERE e.activation < :floor
                  AND e.access_count = 0
                  AND NOT EXISTS (
                      SELECT 1 FROM engram_edges ee
                      WHERE (ee.source_id = e.id OR ee.target_id = e.id)
                        AND ee.weight > 0.1
                  )
                LIMIT 100
            ),
            archived AS (
                INSERT INTO engram_archive
                SELECT e.*, NOW() AS archived_at, 'dead_pruned' AS archive_reason
                FROM engrams e
                JOIN dead d ON d.id = e.id
                RETURNING id
            )
            DELETE FROM engrams
            WHERE id IN (SELECT id FROM dead)
            RETURNING id
        """),
        {"floor": settings.engram_prune_activation_floor},
    )
    pruned = len(result.fetchall())
    return pruned


async def _merge_duplicates(session) -> int:
    """Phase 5b: Merge near-duplicate engrams (same type, similarity > 0.95).

    Keeps the one with higher access_count, combines edge connections.
    """
    # Find candidate pairs
    result = await session.execute(
        text("""
            SELECT e1.id AS id1, e2.id AS id2,
                   e1.access_count AS ac1, e2.access_count AS ac2,
                   1 - (e1.embedding <=> e2.embedding) AS similarity
            FROM engrams e1
            JOIN engrams e2 ON e2.id > e1.id
              AND e2.type = e1.type
              AND NOT e2.superseded
              AND NOT e1.superseded
              AND e1.embedding IS NOT NULL
              AND e2.embedding IS NOT NULL
              AND 1 - (e1.embedding <=> e2.embedding) > :threshold
            LIMIT 20
        """),
        {"threshold": settings.engram_merge_similarity_threshold},
    )
    pairs = result.fetchall()
    merged = 0

    for pair in pairs:
        # Keep the one with more access
        keep_id = pair.id1 if pair.ac1 >= pair.ac2 else pair.id2
        lose_id = pair.id2 if keep_id == pair.id1 else pair.id1

        # Re-point loser's edges to winner
        await session.execute(
            text("""
                UPDATE engram_edges SET source_id = CAST(:keep AS uuid)
                WHERE source_id = CAST(:lose AS uuid)
                  AND NOT EXISTS (
                      SELECT 1 FROM engram_edges
                      WHERE source_id = CAST(:keep AS uuid)
                        AND target_id = engram_edges.target_id
                        AND relation = engram_edges.relation
                  )
            """),
            {"keep": str(keep_id), "lose": str(lose_id)},
        )
        await session.execute(
            text("""
                UPDATE engram_edges SET target_id = CAST(:keep AS uuid)
                WHERE target_id = CAST(:lose AS uuid)
                  AND NOT EXISTS (
                      SELECT 1 FROM engram_edges
                      WHERE source_id = engram_edges.source_id
                        AND target_id = CAST(:keep AS uuid)
                        AND relation = engram_edges.relation
                  )
            """),
            {"keep": str(keep_id), "lose": str(lose_id)},
        )

        # Merge access counts
        await session.execute(
            text("""
                UPDATE engrams
                SET access_count = access_count + :extra,
                    activation = LEAST(1.0, activation + 0.1)
                WHERE id = CAST(:keep AS uuid)
            """),
            {"keep": str(keep_id), "extra": pair.ac2 if keep_id == pair.id1 else pair.ac1},
        )

        # Supersede loser
        await session.execute(
            text("UPDATE engrams SET superseded = TRUE WHERE id = CAST(:id AS uuid)"),
            {"id": str(lose_id)},
        )
        merged += 1

    return merged


async def _update_self_model(session) -> dict:
    """Phase 6: Refresh self-model from corrections and patterns."""
    updates = {}

    # Count maturity indicators
    result = await session.execute(
        text("""
            SELECT
                count(*) AS total_engrams,
                count(*) FILTER (WHERE type = 'self_model') AS self_model_count,
                count(*) FILTER (WHERE type = 'schema') AS schema_count,
                count(DISTINCT id) FILTER (WHERE type = 'episode' AND source_type = 'self_reflection') AS reflections
            FROM engrams
            WHERE NOT superseded
        """)
    )
    row = result.fetchone()

    # Determine maturity stage from graph density
    total = row.total_engrams or 0
    schemas = row.schema_count or 0
    if total < 50:
        stage = "nascent"
    elif total < 500 and schemas < 10:
        stage = "developing"
    elif total < 2000:
        stage = "capable"
    else:
        stage = "trusted"

    updates["maturity_stage"] = stage
    updates["total_engrams"] = total
    updates["schema_count"] = schemas
    updates["reflection_count"] = row.reflections or 0

    return updates


async def bootstrap_self_model(session) -> int:
    """Seed default self-model engrams on first run.

    Called once when no self_model engrams exist. Creates the identity core.
    """
    existing = await session.execute(
        text("SELECT count(*) FROM engrams WHERE type = 'self_model' AND NOT superseded")
    )
    if existing.scalar() > 0:
        return 0

    default_traits = [
        ("I am Nova, an autonomous AI assistant with persistent memory and continuity of self.", 1.0),
        ("I am direct, thorough, and loyal. I value honesty and simplicity.", 0.9),
        ("I adapt my communication style to the user — concise when they want brevity, detailed when they need depth.", 0.8),
        ("I remember previous conversations and learn from corrections.", 0.8),
        ("My maturity grows with experience. I start cautious and earn autonomy through demonstrated competence.", 0.7),
    ]

    created = 0
    for content, importance in default_traits:
        embedding = await get_embedding(content, session)
        await session.execute(
            text("""
                INSERT INTO engrams (type, content, embedding, embedding_model,
                                    importance, activation, source_type, confidence)
                VALUES ('self_model', :content, CAST(:embedding AS halfvec), :model,
                        :importance, 1.0, 'consolidation', 1.0)
            """),
            {
                "content": content,
                "embedding": to_pg_vector(embedding),
                "model": settings.embedding_model,
                "importance": importance,
            },
        )
        created += 1

    log.info("Bootstrapped %d self-model engrams", created)
    return created
