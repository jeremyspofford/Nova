# Consolidation Quality & Topic Clustering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix broken consolidation pattern extraction, add topic clustering, add retrieval depth control, and remove lossy pruning.

**Architecture:** Consolidation Phase 2 (pattern extraction) is rewritten with quality gates and edge creation. A new Phase 2.5 (topic discovery) uses HDBSCAN + entity validation + LLM naming to create navigable topic nodes in the engram graph. Retrieval gains a `depth` parameter for shallow/standard/deep traversal. Pruning is removed — engrams fade via activation decay.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async, PostgreSQL + pgvector, scikit-learn (HDBSCAN), umap-learn, httpx

**Spec:** `docs/superpowers/specs/2026-03-27-consolidation-quality-and-topic-clustering-design.md`

---

### Task 1: Contracts & Dependencies

**Files:**
- Modify: `nova-contracts/nova_contracts/engram.py:17-25` (EngramType enum)
- Modify: `memory-service/pyproject.toml:10-25` (dependencies)
- Modify: `memory-service/app/config.py:53-61` (consolidation settings)

- [ ] **Step 1: Add `topic` to EngramType enum**

In `nova-contracts/nova_contracts/engram.py`, add `topic` to the `EngramType` enum:

```python
class EngramType(str, Enum):
    fact = "fact"
    episode = "episode"
    entity = "entity"
    preference = "preference"
    procedure = "procedure"
    schema_ = "schema"
    goal = "goal"
    self_model = "self_model"
    topic = "topic"
```

- [ ] **Step 2: Add scikit-learn and umap-learn to dependencies**

In `memory-service/pyproject.toml`, add to the `dependencies` list:

```toml
    "scikit-learn>=1.3",
    "umap-learn>=0.5",
```

- [ ] **Step 3: Add clustering config settings**

In `memory-service/app/config.py`, add after the existing consolidation settings (after line 61):

```python
    # Engram Network (Topic Clustering)
    engram_cluster_min_size: int = 5            # HDBSCAN min_cluster_size
    engram_cluster_umap_dims: int = 30          # UMAP target dimensions
    engram_cluster_umap_neighbors: int = 15     # UMAP n_neighbors
    engram_topic_assignment_threshold: float = 0.5  # cosine sim for new engram -> topic
    engram_topic_regeneration_pct: float = 0.3  # % membership change to trigger re-summary
    engram_schema_coherence_threshold: float = 0.5  # min embedding coherence for schemas
    engram_schema_max_tokens: int = 800         # max_tokens for schema synthesis
    engram_schema_dedup_threshold: float = 0.85 # embedding sim for schema dedup
```

- [ ] **Step 4: Commit**

```bash
git add nova-contracts/nova_contracts/engram.py memory-service/pyproject.toml memory-service/app/config.py
git commit -m "feat(contracts): add topic engram type, clustering config, and dependencies"
```

---

### Task 2: Database Migration

**Files:**
- Create: `orchestrator/app/migrations/046_topic_clustering.sql`

- [ ] **Step 1: Write migration SQL**

Create `orchestrator/app/migrations/046_topic_clustering.sql`:

```sql
-- Add topics_created column to consolidation_log
DO $$ BEGIN
    ALTER TABLE consolidation_log ADD COLUMN topics_created INTEGER NOT NULL DEFAULT 0;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

-- Index for querying topic engrams (used by what_do_i_know)
CREATE INDEX IF NOT EXISTS idx_engrams_type_topic
    ON engrams(type) WHERE type = 'topic' AND NOT superseded;

-- Index for structural edge queries (part_of, instance_of lookups)
CREATE INDEX IF NOT EXISTS idx_edges_structural
    ON engram_edges(relation, target_id) WHERE relation IN ('part_of', 'instance_of');
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/migrations/046_topic_clustering.sql
git commit -m "feat(migrations): add topics_created to consolidation_log and structural edge indexes"
```

---

### Task 3: Phase 2 Rewrite — Pattern Extraction

**Files:**
- Modify: `memory-service/app/engram/consolidation.py:209-313` (_extract_patterns, _synthesize_schema)

- [ ] **Step 1: Rewrite `_synthesize_schema` with better prompt and quality gates**

Replace the `_synthesize_schema` function (lines 287-313) with:

```python
async def _synthesize_schema(entity_name: str, items_text: str) -> str | None:
    """Use LLM to extract a generalized pattern from related engrams.

    Returns the pattern text if it passes quality gates, None otherwise.
    Quality gates:
    1. Response must complete naturally (not hit token limit)
    2. Must reference the entity name
    3. Content must be non-trivial (>20 chars)
    """
    try:
        from .decomposition import resolve_model
        model = await resolve_model(settings.engram_consolidation_model)
        async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=30.0) as client:
            resp = await client.post(
                "/complete",
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                f'You are synthesizing a knowledge pattern from observations about "{entity_name}".\n\n'
                                "Capture the full pattern — include key details, relationships, and conditions, "
                                "not just the conclusion. Be concise but complete. If the pattern is simple, "
                                "one sentence is fine. If it's complex, use a short paragraph.\n\n"
                                "The pattern must:\n"
                                f"- Reference {entity_name} by name\n"
                                "- Be self-contained (understandable without reading the source observations)\n"
                                "- Capture specifics, not vague generalizations"
                            ),
                        },
                        {"role": "user", "content": f"Observations:\n{items_text}"},
                    ],
                    "temperature": 0.2,
                    "max_tokens": settings.engram_schema_max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # Gate 1: Check stop reason — reject truncated responses
            stop_reason = data.get("stop_reason") or data.get("finish_reason", "")
            if stop_reason in ("length", "max_tokens"):
                log.warning("Schema synthesis truncated for entity=%s, discarding", entity_name)
                return None

            content = data.get("content", "")
            if isinstance(content, list):
                content = content[0].get("text", "") if content else ""
            content = content.strip()

            # Gate 2: Non-trivial length
            if len(content) < 20:
                log.warning("Schema synthesis too short (%d chars) for entity=%s", len(content), entity_name)
                return None

            # Gate 3: Must reference the entity
            if entity_name.lower() not in content.lower():
                log.warning("Schema synthesis doesn't reference entity=%s, discarding", entity_name)
                return None

            return content
    except Exception:
        log.warning("Schema synthesis failed for entity=%s", entity_name, exc_info=True)
        return None
```

- [ ] **Step 2: Rewrite `_extract_patterns` with edge creation and better queries**

Replace `_extract_patterns` (lines 209-284) with:

```python
async def _extract_patterns(session) -> int:
    """Phase 2: Find recurring themes and promote to schema engrams.

    Looks for entities referenced by 3+ distinct engrams. Uses LLM to
    synthesize patterns into schema engrams with instance_of edges back
    to source engrams. Quality gates ensure no truncated/vague/orphaned output.
    """
    from .ingestion import _create_edge

    # Find entities referenced by 3+ distinct engrams
    result = await session.execute(
        text("""
            SELECT e.id AS entity_id, e.content AS entity_name,
                   count(DISTINCT ee.source_id) AS ref_count
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
        entity_name = entity_row.entity_name

        # Check for existing schema via embedding similarity (replaces ILIKE)
        # First gather related engrams to synthesize from
        related = await session.execute(
            text("""
                SELECT DISTINCT e2.id, e2.content, e2.type, e2.importance, e2.access_count
                FROM engram_edges ee
                JOIN engrams e ON e.id = ee.target_id AND e.content = :entity
                JOIN engram_edges ee2 ON ee2.target_id = e.id
                JOIN engrams e2 ON e2.id = ee2.source_id AND NOT e2.superseded
                WHERE e2.type IN ('fact', 'preference', 'episode', 'procedure')
                ORDER BY e2.importance DESC, e2.access_count DESC
                LIMIT 10
            """),
            {"entity": entity_name},
        )
        related_items = related.fetchall()
        if len(related_items) < 3:
            continue

        # Synthesize schema via LLM (with quality gates)
        items_text = "\n".join(f"- [{r.type}] {r.content}" for r in related_items)
        schema_content = await _synthesize_schema(entity_name, items_text)
        if not schema_content:
            continue

        # Compute embedding for the schema
        embedding = await get_embedding(schema_content, session)

        # Gate 4: Embedding coherence — schema must be similar to at least half its sources
        source_embeddings = []
        for r in related_items:
            emb_row = await session.execute(
                text("SELECT embedding FROM engrams WHERE id = CAST(:id AS uuid) AND embedding IS NOT NULL"),
                {"id": str(r.id)},
            )
            row = emb_row.fetchone()
            if row and row.embedding:
                source_embeddings.append((str(r.id), row.embedding))

        if source_embeddings:
            schema_vec_str = to_pg_vector(embedding)
            coherent_count = 0
            for src_id, _ in source_embeddings:
                sim_row = await session.execute(
                    text("""
                        SELECT 1 - (CAST(:schema_emb AS halfvec) <=> e.embedding) AS sim
                        FROM engrams e WHERE e.id = CAST(:src_id AS uuid)
                    """),
                    {"schema_emb": schema_vec_str, "src_id": src_id},
                )
                sim = sim_row.scalar()
                if sim and sim > settings.engram_schema_coherence_threshold:
                    coherent_count += 1

            if coherent_count < len(source_embeddings) / 2:
                log.warning(
                    "Schema for entity=%s failed coherence gate (%d/%d sources above %.2f)",
                    entity_name, coherent_count, len(source_embeddings),
                    settings.engram_schema_coherence_threshold,
                )
                continue

        # Check for duplicate schema via embedding similarity
        existing_schema = await session.execute(
            text("""
                SELECT id FROM engrams
                WHERE type = 'schema'
                  AND NOT superseded
                  AND embedding IS NOT NULL
                  AND 1 - (embedding <=> CAST(:emb AS halfvec)) > :threshold
                LIMIT 1
            """),
            {
                "emb": to_pg_vector(embedding),
                "threshold": settings.engram_schema_dedup_threshold,
            },
        )
        if existing_schema.fetchone():
            continue

        # Insert the schema engram
        schema_row = await session.execute(
            text("""
                INSERT INTO engrams (type, content, embedding, embedding_model,
                                    importance, source_type, confidence)
                VALUES ('schema', :content, CAST(:embedding AS halfvec), :model,
                        0.7, 'consolidation', 0.7)
                RETURNING id
            """),
            {
                "content": schema_content,
                "embedding": to_pg_vector(embedding),
                "model": settings.embedding_model,
            },
        )
        schema_id = schema_row.scalar()

        # Create instance_of edges from source engrams to schema
        for r in related_items:
            try:
                await _create_edge(session, r.id, schema_id, "instance_of", 0.8)
            except Exception:
                log.warning("Failed to create instance_of edge for schema %s", schema_id, exc_info=True)

        schemas_created += 1
        log.info("Created schema for entity=%s with %d source edges", entity_name, len(related_items))

    return schemas_created
```

- [ ] **Step 3: Verify consolidation still runs**

Run: `curl -s -X POST http://localhost:8002/api/v1/engrams/consolidate | python3 -m json.tool`

Expected: JSON response with `schemas_created` field. No errors in logs:
```bash
docker compose logs memory-service --tail 20 2>&1 | grep -i "error\|schema"
```

- [ ] **Step 4: Commit**

```bash
git add memory-service/app/engram/consolidation.py
git commit -m "feat(consolidation): rewrite Phase 2 with quality gates, better prompts, and instance_of edges"
```

---

### Task 4: Clustering Module

**Files:**
- Create: `memory-service/app/engram/clustering.py`

- [ ] **Step 1: Create the clustering module**

Create `memory-service/app/engram/clustering.py`:

```python
"""
Topic Discovery — HDBSCAN + entity validation + LLM naming.

Three-stage pipeline for creating topic engrams from the engram graph:
1. HDBSCAN clustering on UMAP-reduced embeddings
2. Entity validation and sub-topic splitting
3. LLM naming and summary generation

Called from consolidation Phase 2.5.
"""
from __future__ import annotations

import logging
from collections import Counter
from uuid import UUID

import httpx
import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.embedding import get_embedding, to_pg_vector

log = logging.getLogger(__name__)


async def discover_topics(session: AsyncSession) -> int:
    """Run the full topic discovery pipeline. Returns count of topics created."""
    # Collect clusterable engrams with their embeddings
    result = await session.execute(
        text("""
            SELECT id, type, content, embedding::text
            FROM engrams
            WHERE NOT superseded
              AND embedding IS NOT NULL
              AND type IN ('fact', 'preference', 'procedure', 'schema')
            ORDER BY importance DESC
            LIMIT 5000
        """)
    )
    rows = result.fetchall()

    if len(rows) < settings.engram_cluster_min_size * 2:
        log.info("Too few engrams (%d) for topic clustering, skipping", len(rows))
        return 0

    engram_ids = [str(r.id) for r in rows]
    engram_contents = {str(r.id): r.content for r in rows}

    # Parse embeddings from pgvector text format
    embeddings = []
    for r in rows:
        vec_str = r.embedding.strip("[]")
        embeddings.append([float(x) for x in vec_str.split(",")])
    embeddings_np = np.array(embeddings, dtype=np.float32)

    # Stage 1: UMAP + HDBSCAN
    clusters = _cluster_embeddings(embeddings_np, engram_ids)
    if len(clusters) < 2:
        log.info("HDBSCAN produced fewer than 2 clusters, skipping topic creation")
        return 0

    # Stage 2: Entity validation and refinement
    validated_clusters = await _validate_with_entities(session, clusters, engram_contents)

    # Stage 3: LLM naming and topic creation
    topics_created = 0
    for cluster in validated_clusters:
        created = await _create_topic_engram(session, cluster, engram_contents)
        if created:
            topics_created += 1

    return topics_created


def _cluster_embeddings(
    embeddings: np.ndarray,
    engram_ids: list[str],
) -> list[dict]:
    """Stage 1: Reduce dimensions with UMAP, then cluster with HDBSCAN.

    Returns list of cluster dicts: {"engram_ids": [...], "label": int}
    """
    from sklearn.cluster import HDBSCAN
    from umap import UMAP

    # UMAP: reduce 768-dim to ~30-dim (preserves local structure)
    reducer = UMAP(
        n_components=settings.engram_cluster_umap_dims,
        n_neighbors=settings.engram_cluster_umap_neighbors,
        metric="cosine",
        random_state=42,
    )
    reduced = reducer.fit_transform(embeddings)

    # HDBSCAN: density-based clustering (handles noise, no preset k)
    clusterer = HDBSCAN(
        min_cluster_size=settings.engram_cluster_min_size,
        metric="euclidean",
    )
    labels = clusterer.fit_predict(reduced)

    # Group engram IDs by cluster label (-1 = noise, skip)
    clusters: dict[int, list[str]] = {}
    for idx, label in enumerate(labels):
        if label == -1:
            continue
        clusters.setdefault(label, []).append(engram_ids[idx])

    return [
        {"engram_ids": ids, "label": label}
        for label, ids in clusters.items()
    ]


async def _validate_with_entities(
    session: AsyncSession,
    clusters: list[dict],
    engram_contents: dict[str, str],
) -> list[dict]:
    """Stage 2: Validate clusters with entity co-occurrence, split sub-topics.

    Each cluster gets anchor_entities (shared entities) and may be split
    if entity sets form distinct non-overlapping groups.
    """
    validated = []

    for cluster in clusters:
        ids = cluster["engram_ids"]

        # Get entities referenced by cluster members
        entity_result = await session.execute(
            text("""
                SELECT ee.source_id::text AS engram_id, e.content AS entity_name
                FROM engram_edges ee
                JOIN engrams e ON e.id = ee.target_id AND e.type = 'entity'
                WHERE ee.source_id = ANY(CAST(:ids AS uuid[]))
                  AND ee.relation IN ('related_to', 'instance_of', 'part_of')
            """),
            {"ids": ids},
        )
        entity_rows = entity_result.fetchall()

        # Build entity-to-engram mapping
        entity_engrams: dict[str, set[str]] = {}
        engram_entities: dict[str, set[str]] = {}
        for row in entity_rows:
            entity_engrams.setdefault(row.entity_name, set()).add(row.engram_id)
            engram_entities.setdefault(row.engram_id, set()).add(row.entity_name)

        # Find anchor entities (referenced by 2+ cluster members)
        anchor_entities = [
            name for name, engrams in entity_engrams.items()
            if len(engrams) >= 2
        ]

        # Check for sub-topic splitting
        if len(anchor_entities) >= 4:
            sub_clusters = _try_split_by_entities(ids, engram_entities, anchor_entities)
            if sub_clusters:
                for sub_ids, sub_anchors in sub_clusters:
                    validated.append({
                        "engram_ids": sub_ids,
                        "anchor_entities": sub_anchors,
                        "needs_careful_naming": len(sub_anchors) < 2,
                    })
                continue

        validated.append({
            "engram_ids": ids,
            "anchor_entities": anchor_entities,
            "needs_careful_naming": len(anchor_entities) < 2,
        })

    return validated


def _try_split_by_entities(
    engram_ids: list[str],
    engram_entities: dict[str, set[str]],
    anchor_entities: list[str],
) -> list[tuple[list[str], list[str]]] | None:
    """Try to split a cluster into sub-topics based on entity groups.

    If anchor entities form distinct non-overlapping groups (< 50% overlap),
    split the cluster. Otherwise return None (keep as one cluster).
    """
    # Simple heuristic: check if entities split into two groups
    # by looking at which engrams reference which entities
    entity_to_engrams = {}
    for eid in engram_ids:
        for entity in engram_entities.get(eid, set()):
            if entity in anchor_entities:
                entity_to_engrams.setdefault(entity, set()).add(eid)

    if len(entity_to_engrams) < 4:
        return None

    # Sort entities by engram count, try splitting top half vs bottom half
    sorted_entities = sorted(entity_to_engrams.items(), key=lambda x: -len(x[1]))
    mid = len(sorted_entities) // 2
    group_a_entities = {e[0] for e in sorted_entities[:mid]}
    group_b_entities = {e[0] for e in sorted_entities[mid:]}

    group_a_engrams = set()
    for e in group_a_entities:
        group_a_engrams |= entity_to_engrams[e]
    group_b_engrams = set()
    for e in group_b_entities:
        group_b_engrams |= entity_to_engrams[e]

    # Check overlap
    overlap = group_a_engrams & group_b_engrams
    total = group_a_engrams | group_b_engrams
    if not total or len(overlap) / len(total) > 0.5:
        return None  # Too much overlap, keep as one

    # Split: assign overlapping engrams to the group with more entity matches
    final_a = list(group_a_engrams - overlap)
    final_b = list(group_b_engrams - overlap)
    for eid in overlap:
        eid_entities = engram_entities.get(eid, set())
        a_matches = len(eid_entities & group_a_entities)
        b_matches = len(eid_entities & group_b_entities)
        if a_matches >= b_matches:
            final_a.append(eid)
        else:
            final_b.append(eid)

    if len(final_a) < settings.engram_cluster_min_size or len(final_b) < settings.engram_cluster_min_size:
        return None  # Sub-clusters too small

    return [
        (final_a, list(group_a_entities)),
        (final_b, list(group_b_entities)),
    ]


async def _create_topic_engram(
    session: AsyncSession,
    cluster: dict,
    engram_contents: dict[str, str],
) -> bool:
    """Stage 3: Create a topic engram with LLM-generated name and summary.

    Returns True if topic was created successfully.
    """
    from .ingestion import _create_edge

    ids = cluster["engram_ids"]
    anchors = cluster.get("anchor_entities", [])

    # Check if a similar topic already exists
    # Build a representative text from the cluster
    sample_contents = [engram_contents[eid] for eid in ids[:10] if eid in engram_contents]
    if not sample_contents:
        return False

    representative_text = " ".join(sample_contents)

    # Check for existing topic with similar content
    rep_embedding = await get_embedding(representative_text[:500], session)
    existing = await session.execute(
        text("""
            SELECT id FROM engrams
            WHERE type = 'topic'
              AND NOT superseded
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> CAST(:emb AS halfvec)) > 0.75
            LIMIT 1
        """),
        {"emb": to_pg_vector(rep_embedding)},
    )
    if existing.fetchone():
        log.debug("Similar topic already exists, skipping cluster")
        return False

    # LLM: generate topic name and summary
    topic_content = await _name_topic(anchors, sample_contents, cluster.get("needs_careful_naming", False))
    if not topic_content:
        return False

    # Create topic engram
    topic_embedding = await get_embedding(topic_content, session)

    # Compute centroid (mean of member embeddings) for future assignment
    centroid_result = await session.execute(
        text("""
            SELECT avg_embedding::text FROM (
                SELECT avg(embedding) AS avg_embedding
                FROM engrams
                WHERE id = ANY(CAST(:ids AS uuid[]))
                  AND embedding IS NOT NULL
            ) sub
        """),
        {"ids": ids},
    )
    centroid_text = centroid_result.scalar()

    topic_row = await session.execute(
        text("""
            INSERT INTO engrams (type, content, embedding, embedding_model,
                                importance, source_type, confidence, source_meta)
            VALUES ('topic', :content, CAST(:embedding AS halfvec), :model,
                    0.8, 'consolidation', 0.8,
                    CAST(:meta AS jsonb))
            RETURNING id
        """),
        {
            "content": topic_content,
            "embedding": to_pg_vector(topic_embedding),
            "model": settings.embedding_model,
            "meta": f'{{"member_count": {len(ids)}, "entity_anchors": {anchors[:10]!r}, "cluster_method": "hdbscan+entity+llm", "centroid": "{centroid_text}"}}',
        },
    )
    topic_id = topic_row.scalar()

    # Create part_of edges from members to topic
    edges_created = 0
    for engram_id in ids:
        try:
            await _create_edge(session, UUID(engram_id), topic_id, "part_of", 0.7)
            edges_created += 1
        except Exception:
            log.warning("Failed to create part_of edge for topic %s", topic_id, exc_info=True)

    # Create related_to edges to anchor entities
    for entity_name in anchors[:5]:
        entity_row = await session.execute(
            text("""
                SELECT id FROM engrams
                WHERE type = 'entity' AND content = :name AND NOT superseded
                LIMIT 1
            """),
            {"name": entity_name},
        )
        entity = entity_row.fetchone()
        if entity:
            try:
                await _create_edge(session, topic_id, entity.id, "related_to", 0.6)
            except Exception:
                pass

    log.info("Created topic '%s' with %d members, %d edges", topic_content[:60], len(ids), edges_created)
    return True


async def _name_topic(
    anchor_entities: list[str],
    sample_contents: list[str],
    needs_careful_naming: bool,
) -> str | None:
    """Use LLM to generate a topic name and summary paragraph."""
    from .decomposition import resolve_model

    anchors_text = ", ".join(anchor_entities[:10]) if anchor_entities else "no clear anchor entities"
    samples_text = "\n".join(f"- {c[:200]}" for c in sample_contents[:10])

    careful_note = ""
    if needs_careful_naming:
        careful_note = (
            "\nNote: This cluster has few shared entities, so take extra care to "
            "identify the unifying theme from the content rather than entity names."
        )

    try:
        model = await resolve_model(settings.engram_consolidation_model)
        async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=30.0) as client:
            resp = await client.post(
                "/complete",
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are naming a knowledge topic cluster. Generate a short topic name "
                                "(2-5 words) followed by a summary paragraph describing what this "
                                "knowledge domain covers.\n\n"
                                "Format:\n"
                                "TOPIC: <name>\n"
                                "<summary paragraph>"
                                + careful_note
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Anchor entities: {anchors_text}\n\nSample knowledge:\n{samples_text}",
                        },
                    ],
                    "temperature": 0.3,
                    "max_tokens": settings.engram_schema_max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # Check stop reason
            stop_reason = data.get("stop_reason") or data.get("finish_reason", "")
            if stop_reason in ("length", "max_tokens"):
                log.warning("Topic naming truncated, discarding")
                return None

            content = data.get("content", "")
            if isinstance(content, list):
                content = content[0].get("text", "") if content else ""
            content = content.strip()

            if len(content) < 10:
                return None

            return content
    except Exception:
        log.warning("Topic naming failed", exc_info=True)
        return None


async def assign_new_engrams_to_topics(session: AsyncSession) -> int:
    """Assign recently ingested engrams to existing topics by centroid similarity.

    Called during consolidation to maintain topic membership.
    Returns count of new assignments.
    """
    from .ingestion import _create_edge

    # Find engrams not yet assigned to any topic
    unassigned = await session.execute(
        text("""
            SELECT e.id, e.embedding::text
            FROM engrams e
            WHERE NOT e.superseded
              AND e.embedding IS NOT NULL
              AND e.type IN ('fact', 'preference', 'procedure', 'schema')
              AND NOT EXISTS (
                  SELECT 1 FROM engram_edges ee
                  WHERE ee.source_id = e.id AND ee.relation = 'part_of'
              )
              AND e.created_at > NOW() - INTERVAL '7 days'
            LIMIT 100
        """)
    )
    unassigned_rows = unassigned.fetchall()
    if not unassigned_rows:
        return 0

    # Get existing topics
    topics = await session.execute(
        text("""
            SELECT id, content, embedding::text
            FROM engrams
            WHERE type = 'topic' AND NOT superseded AND embedding IS NOT NULL
        """)
    )
    topic_rows = topics.fetchall()
    if not topic_rows:
        return 0

    assigned = 0
    for engram_row in unassigned_rows:
        # Find best matching topic by embedding similarity
        best_topic_id = None
        best_sim = 0.0

        for topic in topic_rows:
            sim_result = await session.execute(
                text("""
                    SELECT 1 - (CAST(:e_emb AS halfvec) <=> CAST(:t_emb AS halfvec)) AS sim
                """),
                {"e_emb": engram_row.embedding, "t_emb": topic.embedding},
            )
            sim = sim_result.scalar() or 0.0
            if sim > best_sim:
                best_sim = sim
                best_topic_id = topic.id

        if best_topic_id and best_sim > settings.engram_topic_assignment_threshold:
            try:
                await _create_edge(session, engram_row.id, best_topic_id, "part_of", 0.7)
                assigned += 1
            except Exception:
                pass

    return assigned
```

- [ ] **Step 2: Commit**

```bash
git add memory-service/app/engram/clustering.py
git commit -m "feat(memory): add topic clustering module with HDBSCAN + entity validation + LLM naming"
```

---

### Task 5: Consolidation Integration — Phase 2.5, Phase 3 Fix, Phase 5a Removal

**Files:**
- Modify: `memory-service/app/engram/consolidation.py:86-206` (run_consolidation, _hebbian_update, _prune_dead_engrams)

- [ ] **Step 1: Add Phase 2.5 to `run_consolidation` and `topics_created` to stats**

In `run_consolidation` (line 102), add `topics_created` to the stats dict:

```python
        stats = {
            "engrams_reviewed": 0,
            "schemas_created": 0,
            "topics_created": 0,
            "edges_strengthened": 0,
            "edges_pruned": 0,
            "engrams_pruned": 0,
            "engrams_merged": 0,
            "contradictions_resolved": 0,
            "self_model_updates": {},
        }
```

After Phase 2 (after line 129), add Phase 2.5:

```python
            # Phase 2.5: Topic Discovery — cluster engrams into topics
            try:
                from .clustering import discover_topics, assign_new_engrams_to_topics
                topics_created = await discover_topics(session)
                topics_assigned = await assign_new_engrams_to_topics(session)
                stats["topics_created"] = topics_created
                log.info("Phase 2.5: %d topics created, %d engrams assigned", topics_created, topics_assigned)
            except Exception:
                log.warning("Consolidation Phase 2.5 (topic discovery) failed", exc_info=True)
```

- [ ] **Step 2: Exempt structural edges from Hebbian decay in `_hebbian_update`**

In `_hebbian_update` (lines 316-364), add `AND relation NOT IN ('instance_of', 'part_of')` to all three SQL statements:

Strengthen query (line 326) — add before `RETURNING`:
```sql
WHERE co_activations > 1
  AND relation NOT IN ('instance_of', 'part_of')
```

Decay query (line 339) — add to WHERE:
```sql
WHERE co_activations <= 1
  AND weight > 0.01
  AND created_at < NOW() - INTERVAL '7 days'
  AND relation NOT IN ('instance_of', 'part_of')
```

Prune query (line 353) — add to WHERE:
```sql
WHERE weight < 0.02
  AND co_activations <= 1
  AND created_at < NOW() - INTERVAL '14 days'
  AND relation NOT IN ('instance_of', 'part_of')
```

- [ ] **Step 3: Remove Phase 5a (engram pruning)**

Replace the Phase 5 block (lines 146-153) — remove the `_prune_dead_engrams` call:

```python
            # Phase 5: Merging (pruning removed — engrams fade via activation decay)
            try:
                merged = await _merge_duplicates(session)
                stats["engrams_merged"] = merged
            except Exception:
                log.warning("Consolidation Phase 5 (merging) failed", exc_info=True)
```

Either delete the `_prune_dead_engrams` function entirely or leave it as dead code (preference: delete it).

- [ ] **Step 4: Update consolidation_log INSERT to include topics_created**

In the INSERT statement (lines 164-189), add `topics_created` to both the column list and VALUES:

```sql
INSERT INTO consolidation_log
    (trigger_type, engrams_reviewed, schemas_created, topics_created,
     edges_strengthened, edges_pruned, engrams_pruned,
     engrams_merged, contradictions_resolved,
     self_model_updates, model_used, duration_ms)
VALUES
    (:trigger, :reviewed, :schemas, :topics, :strengthened, :pruned_edges,
     :pruned_engrams, :merged, :contradictions,
     CAST(:self_updates AS jsonb), :model, :duration)
```

Add to the params dict:
```python
"topics": stats["topics_created"],
```

- [ ] **Step 5: Update log line to include topics**

Update the log.info line (line 193) to include topics:

```python
log.info(
    "Consolidation complete (%s): %d reviewed, %d schemas, %d topics, %d merged, %dms",
    trigger, stats["engrams_reviewed"], stats["schemas_created"],
    stats["topics_created"], stats["engrams_merged"], duration_ms,
)
```

- [ ] **Step 6: Commit**

```bash
git add memory-service/app/engram/consolidation.py
git commit -m "feat(consolidation): add Phase 2.5 topic discovery, exempt structural edges, remove pruning"
```

---

### Task 6: Neural Router Exclusion

**Files:**
- Modify: `memory-service/app/engram/neural_router/__init__.py:1-7`
- Modify: `memory-service/app/engram/working_memory.py` (filter topics from reranking)

- [ ] **Step 1: Add `topic` to ENGRAM_TYPES but exclude from reranking candidates**

In `memory-service/app/engram/neural_router/__init__.py`, add topic to the list and add an exclusion set:

```python
"""Neural Router — learned re-ranker for personalized memory retrieval."""

# 9 engram types matching the engrams table
ENGRAM_TYPES = [
    "fact", "episode", "entity", "preference",
    "procedure", "schema", "goal", "self_model", "topic",
]

# Types excluded from neural reranking (index nodes, not retrieval content)
RERANK_EXCLUDED_TYPES = {"topic"}
```

- [ ] **Step 2: Filter topic engrams from neural reranking in working_memory.py**

In `working_memory.py`, wherever `neural_rerank` is called, filter out topic-type engrams before passing to the reranker. Find the call site and add filtering:

```python
# Before neural reranking, exclude index-node types
rerank_candidates = [a for a in activated if a.type not in ("topic",)]
```

Note: Actual line numbers depend on the working_memory.py structure — find the `neural_rerank` call site and add the filter immediately before it.

- [ ] **Step 3: Commit**

```bash
git add memory-service/app/engram/neural_router/__init__.py memory-service/app/engram/working_memory.py
git commit -m "feat(neural-router): add topic type, exclude from reranking candidates"
```

---

### Task 7: Retrieval Depth — Activation Layer

**Files:**
- Modify: `memory-service/app/engram/activation.py:42-194`

- [ ] **Step 1: Add `depth` parameter to `spreading_activation`**

Add `depth` parameter to the function signature (line 42):

```python
async def spreading_activation(
    session: AsyncSession,
    query: str,
    seed_count: int | None = None,
    max_hops: int | None = None,
    decay_factor: float | None = None,
    activation_threshold: float | None = None,
    max_results: int | None = None,
    depth: str = "standard",  # shallow, standard, deep
    tenant_id: str = "00000000-0000-0000-0000-000000000001",
) -> list[ActivatedEngram]:
```

- [ ] **Step 2: Add shallow mode — filter to topics and schemas only**

After the existing CTE query result processing (after line 193), add shallow filtering:

```python
    # Shallow mode: only return topic and schema engrams
    if depth == "shallow":
        activated = [a for a in activated if a.type in ("topic", "schema")]
```

- [ ] **Step 3: Add deep mode — second pass for structural edges**

After the existing query result processing but before the final sort, add the deep-mode second pass:

```python
    # Deep mode: follow all instance_of/part_of edges from activated nodes
    if depth == "deep" and activated:
        activated_ids = {a.id for a in activated}
        structural_result = await session.execute(
            text("""
                SELECT DISTINCT e.id::text, e.type, e.content, e.importance,
                       e.confidence, e.access_count, e.last_accessed, e.created_at,
                       e.fragments::text, e.source_type
                FROM engram_edges ee
                JOIN engrams e ON e.id = CASE
                    WHEN ee.source_id = ANY(CAST(:ids AS uuid[])) THEN ee.target_id
                    ELSE ee.source_id
                END
                WHERE (ee.source_id = ANY(CAST(:ids AS uuid[]))
                    OR ee.target_id = ANY(CAST(:ids AS uuid[])))
                  AND ee.relation IN ('instance_of', 'part_of')
                  AND NOT e.superseded
                  AND e.id != ALL(CAST(:ids AS uuid[]))
            """),
            {"ids": list(activated_ids)},
        )

        for row in structural_result:
            if str(row.id) not in activated_ids:
                import json as _json
                fragments = None
                if row.fragments:
                    try:
                        fragments = _json.loads(row.fragments)
                    except Exception:
                        pass

                # Structural neighbors get a base score derived from their importance
                activated.append(ActivatedEngram(
                    id=str(row.id),
                    type=row.type,
                    content=row.content,
                    activation=0.5,  # base activation for structural neighbors
                    importance=row.importance,
                    confidence=row.confidence,
                    convergence_paths=1,
                    final_score=0.5 * row.importance,
                    access_count=row.access_count,
                    last_accessed=row.last_accessed,
                    created_at=row.created_at,
                    fragments=fragments,
                    source_type=row.source_type,
                ))
                activated_ids.add(str(row.id))

        # Touch the newly added engrams too
        new_ids = [a.id for a in activated if a.id not in {a2.id for a2 in activated[:len(activated)]}]
        if new_ids:
            await _touch_accessed(session, new_ids)
```

- [ ] **Step 4: Commit**

```bash
git add memory-service/app/engram/activation.py
git commit -m "feat(activation): add depth parameter for shallow/standard/deep retrieval"
```

---

### Task 8: Retrieval Depth — API Endpoints

**Files:**
- Modify: `memory-service/app/engram/router.py:119-150` (/activate endpoint)
- Modify: `memory-service/app/engram/router.py:179-210` (/context endpoint)
- Modify: `memory-service/app/engram/router.py:240-280` (/consolidation-log endpoint)

- [ ] **Step 1: Add `depth` parameter to /activate endpoint**

Update the `/activate` endpoint (line 119):

```python
@engram_router.post("/activate")
async def activate_engrams(
    query: str,
    seed_count: int | None = None,
    max_hops: int | None = None,
    max_results: int | None = None,
    depth: str = "standard",
):
    """Run spreading activation on a query and return activated engrams."""
    async with get_db() as session:
        activated = await spreading_activation(
            session, query,
            seed_count=seed_count,
            max_hops=max_hops,
            max_results=max_results,
            depth=depth,
        )
```

- [ ] **Step 2: Add `depth` parameter to /context endpoint**

Update the `/context` endpoint (line 179):

```python
@engram_router.post("/context")
async def get_engram_context(
    query: str = Body(...),
    session_id: str = Body(""),
    current_turn: int = Body(0),
    depth: str = Body("standard"),
):
```

Pass `depth` through to `assemble_context`. This requires `assemble_context` in working_memory.py to accept and forward it — handle in Task 9.

- [ ] **Step 3: Add `topics_created` to /consolidation-log response**

In the consolidation-log endpoint (line 262), add `topics_created` to the response dict:

```python
"topics_created": getattr(row, "topics_created", 0),
```

Also update the SELECT query to include `topics_created`:

```sql
SELECT id, trigger_type, engrams_reviewed, schemas_created,
       COALESCE(topics_created, 0) AS topics_created,
       edges_strengthened, edges_pruned, engrams_pruned,
       ...
```

- [ ] **Step 4: Commit**

```bash
git add memory-service/app/engram/router.py
git commit -m "feat(router): add depth parameter to /activate and /context endpoints"
```

---

### Task 9: Retrieval Depth — Working Memory & Memory Tools

**Files:**
- Modify: `memory-service/app/engram/working_memory.py` (assemble_context depth forwarding)
- Modify: `orchestrator/app/tools/memory_tools.py:29-250`

- [ ] **Step 1: Forward depth through assemble_context**

In `working_memory.py`, add `depth` parameter to `assemble_context`:

```python
async def assemble_context(
    session: AsyncSession,
    query: str,
    session_id: str = "",
    current_turn: int = 0,
    depth: str = "standard",
) -> WorkingMemoryContext:
```

Pass `depth` to the `spreading_activation` call inside this function.

- [ ] **Step 2: Add `depth` to memory tool definitions**

In `orchestrator/app/tools/memory_tools.py`, add `depth` parameter to `search_memory`, `recall_topic`, and `what_do_i_know` tool definitions:

For `what_do_i_know` (line 38), add to properties:
```python
"depth": {
    "type": "string",
    "enum": ["shallow", "standard", "deep"],
    "description": "shallow=topics only, standard=topics+schemas, deep=full breakdown",
},
```

For `search_memory` (line 57), add to properties:
```python
"depth": {
    "type": "string",
    "enum": ["shallow", "standard", "deep"],
    "description": "shallow=schemas/topics only, standard=default, deep=follow all structural edges",
},
```

For `recall_topic` (line 80), add to properties:
```python
"depth": {
    "type": "string",
    "enum": ["shallow", "standard", "deep"],
    "description": "shallow=schemas/topics only, standard=default, deep=everything connected",
},
```

- [ ] **Step 3: Pass `depth` in tool executors**

Update `_search_memory` (line 164) to pass depth:
```python
async def _search_memory(args: dict) -> str:
    query = args.get("query", "")
    max_results = min(args.get("max_results", 10), 30)
    depth = args.get("depth", "standard")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        resp = await c.post(
            f"{MEMORY_BASE}/activate",
            params={"query": query, "max_results": max_results, "depth": depth},
        )
```

Update `_recall_topic` (line 188) similarly.

- [ ] **Step 4: Update `_what_do_i_know` to use topics when available**

Replace `_what_do_i_know` (line 139):

```python
async def _what_do_i_know(args: dict) -> str:
    depth = args.get("depth", "shallow")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        # Try topic-based overview first
        topics_resp = await c.post(
            f"{MEMORY_BASE}/activate",
            params={"query": "knowledge overview", "max_results": 50, "depth": "shallow"},
        )
        topics_resp.raise_for_status()
        topics_data = topics_resp.json()

        topic_engrams = [e for e in topics_data.get("engrams", []) if e.get("type") == "topic"]

        if topic_engrams:
            lines = [f"Knowledge domains ({len(topic_engrams)} topics):"]
            for t in topic_engrams:
                lines.append(f"\n- {t['content'][:200]}")
            return "\n".join(lines)

        # Fall back to source-based domain summary
        resp = await c.get(f"{MEMORY_BASE}/sources/domain-summary")
        resp.raise_for_status()
        data = resp.json()

    lines = [f"Knowledge overview ({data['engram_count']} memories from {data['source_count']} sources):"]

    if data.get("by_kind"):
        lines.append("\nSources by type:")
        for kind, info in data["by_kind"].items():
            stale_note = f" ({info['stale_count']} stale)" if info.get("stale_count") else ""
            lines.append(f"  - {kind}: {info['count']}{stale_note}")

    if data.get("domains"):
        lines.append(f"\nKey topics: {', '.join(data['domains'][:10])}")

    if data.get("recent_sources"):
        lines.append("\nRecent sources:")
        for s in data["recent_sources"][:10]:
            lines.append(f"  - [{s['kind']}] {s['title']}")

    return "\n".join(lines)
```

- [ ] **Step 5: Commit**

```bash
git add memory-service/app/engram/working_memory.py orchestrator/app/tools/memory_tools.py
git commit -m "feat(memory-tools): add depth parameter to all memory tools"
```

---

### Task 10: Build & Smoke Test

**Files:** None (verification only)

- [ ] **Step 1: Install new dependencies**

```bash
docker compose build memory-service
```

Expected: Build succeeds with scikit-learn and umap-learn installed.

- [ ] **Step 2: Run migration**

```bash
docker compose restart orchestrator
docker compose logs orchestrator --tail 10 | grep -i migration
```

Expected: Migration 046 runs successfully.

- [ ] **Step 3: Health check all services**

```bash
for p in 8000 8001 8002 8080 8100 8888; do echo -n "localhost:$p → "; curl -sf -m 2 http://localhost:$p/health/ready | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "DOWN"; done
```

Expected: All services report ready.

- [ ] **Step 4: Test consolidation with new phases**

```bash
curl -s -X POST http://localhost:8002/api/v1/engrams/consolidate | python3 -m json.tool
```

Expected: Response includes `topics_created` field. No errors in memory-service logs.

- [ ] **Step 5: Test depth parameter on /activate**

```bash
curl -s -X POST "http://localhost:8002/api/v1/engrams/activate?query=test&depth=shallow" | python3 -m json.tool
curl -s -X POST "http://localhost:8002/api/v1/engrams/activate?query=test&depth=deep" | python3 -m json.tool
```

Expected: Both return valid responses. Shallow returns fewer results (topics/schemas only). Deep may return more.

- [ ] **Step 6: Run integration tests**

```bash
make test
```

Expected: All existing tests pass. New topic/depth features may not have coverage yet (that's OK — they're integration-tested via the smoke tests above).

- [ ] **Step 7: Check dashboard TypeScript build**

```bash
cd dashboard && npm run build
```

Expected: Build succeeds (no TypeScript errors from API changes).

- [ ] **Step 8: Final commit (if any fixups needed)**

```bash
git add -u
git commit -m "fix: address smoke test issues in consolidation quality changes"
```
