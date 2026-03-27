# Consolidation Quality & Topic Clustering

**Date:** 2026-03-27
**Status:** Approved
**Scope:** Fix Phase 2 pattern extraction + add topic clustering to consolidation pipeline

## Problem

Consolidation Phase 2 (pattern extraction) produces low-quality, unusable schema engrams:

1. **Orphaned nodes** — Schema engrams are inserted with zero edges. The `instance_of` edge type exists in contracts but is never used. Spreading activation can't reach them.
2. **Truncated content** — `max_tokens=200` causes mid-sentence cutoffs. No stop_reason validation — truncated output is stored as-is.
3. **Vague abstractions** — The synthesis prompt is 13 words with no format constraints, producing content like "Generalized Pattern: Infrastructure-based verification systems that replace spatial reasoning with explicit coordinate APIs..."
4. **No graph structure** — The engram graph has no mid-level organization. Individual engrams exist, entities link them loosely, but there are no topic-level groupings that would make the graph navigable.

## Core Principle

**Consolidation organizes, never summarizes.** Schemas and topics are index nodes with edges to their source engrams. Nothing is deleted or compressed. The lossless chain:

```
Topic ("AWS Infrastructure")
  ^                          Edge direction: source_id -> target_id
  |-- part_of -- Schema      (schema.id -> topic.id, "schema is part_of topic")
  |               ^
  |               |-- instance_of -- fact engram    (fact.id -> schema.id, "fact is instance_of schema")
  |               |                    |
  |               |                    +-- source_ref_id -> source (full chat transcript)
  |               |-- instance_of -- fact engram
  |               |-- instance_of -- episode engram
  |-- part_of -- Schema
                  ^
                  |-- instance_of -- preference engram
                  |-- instance_of -- fact engram
```

Edge direction convention: `source_id` is the child/member, `target_id` is the parent/group. "A is part_of B" means `source_id=A, target_id=B`. Spreading activation traverses edges bidirectionally, so direction affects semantics but not reachability.

Every level is traversable. Quick retrieval grabs schemas. Deep retrieval follows edges to source engrams. Full retrieval goes to source content via `read_source`. Nothing is lost at any layer.

## Design

### 1. Data Model

**New engram type: `topic`**

Added to engram type enum in contracts. A topic node holds:
- `content`: LLM-generated name + summary paragraph
- `embedding`: for direct similarity retrieval
- `importance`: starts at 0.8, adjustable via outcome feedback
- `source_type`: `consolidation`
- `source_meta`: `{"member_count": N, "entity_anchors": ["Lambda", "S3", ...], "cluster_method": "hdbscan+entity+llm"}`

**Edge structure:**

| Edge | Direction | Weight | Purpose |
|------|-----------|--------|---------|
| `part_of` | member -> topic | 0.7 | Topic membership |
| `instance_of` | source engram -> schema | 0.8 | Schema provenance |
| `related_to` | topic -> anchor entity | 0.6 | Entity-topic association |

All edge types participate in spreading activation. Query hits a fact engram -> activation spreads up through `instance_of` to schema -> `part_of` to topic -> back down to sibling engrams in the same topic.

**No new tables.** Topics and schemas are engrams. Membership is edges. Everything goes through existing graph infrastructure.

### 2. Phase 2 Rewrite: Pattern Extraction

**Source selection:** Replace arbitrary `LIMIT 10` with importance + access_count ordering. Include entity name and type of each source engram for richer context.

**Synthesis prompt:**
```
You are synthesizing a knowledge pattern from observations about "{entity_name}".

Capture the full pattern -- include key details, relationships, and conditions,
not just the conclusion. Be concise but complete. If the pattern is simple,
one sentence is fine. If it's complex, use a short paragraph.

The pattern must:
- Reference {entity_name} by name
- Be self-contained (understandable without reading the source observations)
- Capture specifics, not vague generalizations
```

**Max tokens: 800.** Generous headroom. The prompt constrains length through instruction, not token limit.

**Quality gate (all three must pass):**

1. **Stop reason** — Response must complete naturally (`end_turn`/`stop`), not hit token limit. If truncated, discard.
2. **Entity reference** — Output must contain the entity name (case-insensitive). If it drifted so far it doesn't mention the entity, discard.
3. **Embedding coherence** — Schema embedding must have cosine similarity > 0.5 with at least half its source engrams. Catches semantic drift. (0.3 is too weak in 768-dim space where random vectors cluster near 0; 0.5 is a meaningful threshold.)

Future option: add LLM self-critique pass (second call scoring specificity/actionability 1-5, discard if < 3). Not in initial implementation but the gate is designed to accommodate it.

**Edge creation:**
```python
for source_engram_id in source_ids:
    await _create_edge(session, source_engram_id, schema_id, "instance_of", 0.8)
```

**Duplicate detection:** Replace `ILIKE` content match with embedding similarity check (> 0.85 to existing schema for same entity). Update existing schema if new synthesis is better (higher coherence score), don't create duplicates.

### 3. New Phase 2.5: Topic Discovery

Three-stage clustering pipeline:

**Stage 1: Embedding clustering (HDBSCAN)**
- Collect all non-superseded engrams of types `fact`, `preference`, `procedure`, `schema`
- Skip `entity`, `self_model`, `goal` (structural, not topical)
- **Dimensionality reduction:** HDBSCAN fails on raw 768-dim vectors (density estimation breaks down — distances become nearly uniform). Reduce to ~30 dimensions via UMAP before clustering. UMAP preserves local structure well and is the standard pairing with HDBSCAN. Add `umap-learn` as a dependency.
- Run HDBSCAN with `min_cluster_size=5` on the reduced embeddings
- **Minimum viability gate:** If HDBSCAN produces fewer than 2 clusters (everything is noise), skip topic creation for this cycle — the engram set isn't large or diverse enough yet
- Noise points (unclustered) are fine -- not everything needs a topic
- Output: candidate clusters as lists of engram IDs

**Stage 2: Entity validation & refinement**
- For each candidate cluster, gather entities referenced by member engrams
- If cluster members share 2+ common entities, cluster is validated; shared entities become "anchor entities" for naming
- If no shared entities, cluster is still valid (abstract topic) but flagged for more careful LLM naming
- **Sub-topic splitting:** If a cluster's entity sets form distinct non-overlapping groups (e.g., cluster has both {pandas, numpy, matplotlib} and {FastAPI, SQLAlchemy, Jinja2} with no overlap), re-cluster within it using entity co-occurrence as the feature space. Each sub-group becomes its own candidate cluster. If entity groups overlap significantly (>50% shared), keep as one cluster.

**Stage 3: LLM naming & summary**
- For each validated cluster, send anchor entities + 5-10 representative engrams (highest importance) to the LLM
- Prompt asks for: topic name (2-5 words) and summary paragraph
- Same quality gates as schema creation: stop_reason check, minimum length, embedding coherence against cluster centroid
- **Centroid definition:** The cluster centroid is the mean of member embeddings (computed in full 768-dim space), NOT the topic's own content embedding. The topic content embedding is for retrieval; the centroid is for membership checks. Store the centroid as a separate column in `source_meta` for reuse without recomputation.

**Topic maintenance (subsequent consolidation cycles):**
- New engrams: check embedding similarity to existing topic centroids. If > 0.5, assign via `part_of` edge
- Stragglers near boundaries: LLM adjudicates ("does this belong to Topic X, Y, or neither?")
- Topics losing members below `min_cluster_size` dissolve -- members become unaffiliated, never deleted
- Topic summaries regenerated when member composition changes >30%

### 4. Pruning Removal & Structural Edge Protection

**Phase 5a (`_prune_dead_engrams`) removed entirely.** Engrams fade naturally through activation decay. An engram with 0.01 activation and no strong edges is effectively invisible unless directly relevant to a query -- which is exactly when you'd want it.

Deletion trades information for marginal performance. That violates the lossless principle.

**Phase 5b (duplicate merging) stays.** True duplicates (>0.95 similarity, same type) are noise, not information. Dedup is not information loss.

The `engram_archive` table remains as infrastructure but nothing moves into it during normal consolidation.

**Phase 3 (Hebbian) must exempt structural edges.** The existing Hebbian decay (`weight * 0.95` per cycle) and edge pruning (`DELETE WHERE weight < 0.02`) would eventually destroy the `instance_of` and `part_of` edges this design depends on. An `instance_of` edge at weight 0.8, if never co-activated, decays below 0.02 in ~180 cycles and gets deleted — orphaning the schema again.

Fix: Hebbian decay and edge pruning queries must exclude structural relation types:
```sql
WHERE relation NOT IN ('instance_of', 'part_of')
```

These edges represent structural provenance, not learned associations. They should not decay. They were created by consolidation as organizational scaffolding, and their weight reflects certainty of the relationship (0.8 = "this fact was used to synthesize this schema"), not co-activation strength.

### 5. Retrieval Depth Control

**`depth` parameter on memory tools and API endpoints:**

| Depth | Behavior | Use case |
|-------|----------|----------|
| `shallow` | Topics and schemas only | "Do I know anything about X?" |
| `standard` | Current behavior + schemas/topics | Default retrieval |
| `deep` | Follow all `instance_of`/`part_of` edges exhaustively | "Tell me everything about X" |

**Endpoints affected:**
- `POST /api/v1/engrams/context` — accepts `depth` parameter
- `POST /api/v1/engrams/activate` — accepts `depth` parameter

**Memory tools affected:**
- `search_memory(query, depth="standard")` — all three levels
- `recall_topic(entity, depth="standard")` — all three levels
- `what_do_i_know(depth="shallow")` — shallow returns topic list with member counts, standard adds schema summaries, deep adds full breakdown

**`what_do_i_know` endpoint change:** Currently hits `/sources/domain-summary` which aggregates by source kind and knows nothing about topics. Add a new query path: when topics exist, `what_do_i_know` queries engrams WHERE `type='topic'`, counts `part_of` edges for member counts, and returns the topic-based overview. Falls back to source-based domain summary when no topics exist yet (pre-first-clustering).

**Token budgets apply to the engram navigation layer only.** The `read_source` tool always returns full source content without truncation. Engrams are index cards for finding knowledge; sources are the knowledge itself.

**Implementation:** Depth control lives in the memory service. The spreading activation query already traverses edges bidirectionally via the recursive CTE. For `deep` mode, use a two-pass strategy:
1. Standard spreading activation (respects threshold) to find the relevant subgraph
2. Second pass: from all activated nodes, follow `instance_of` and `part_of` edges exhaustively (no activation threshold) to collect the full structural neighborhood

This avoids modifying the core CTE with edge-type-conditional thresholds. The second pass is a simple non-recursive query joining on the activated node set.

### 6. Pruning Safety for Schemas and Topics

Even without general pruning, schemas and topics need lifecycle rules:

- **Schemas** can be superseded only if a newer schema covers the same ground (embedding similarity > 0.85 + same entity anchors). Superseded schema's `instance_of` edges get re-pointed to the replacement.
- **Topics** dissolve only when member count drops below `min_cluster_size`. Remaining members become unaffiliated, never deleted.

## Files Changed

| File | Change |
|------|--------|
| `memory-service/app/engram/consolidation.py` | Phase 2 rewrite, new Phase 2.5, remove Phase 5a, exempt structural edges in Phase 3 |
| `memory-service/app/engram/clustering.py` | **New** — UMAP + HDBSCAN + entity validation + LLM naming |
| `memory-service/app/engram/activation.py` | Depth parameter support (two-pass for deep mode) |
| `memory-service/app/engram/router.py` | Depth parameter on endpoints |
| `memory-service/app/engram/working_memory.py` | Depth-aware context building |
| `memory-service/app/engram/neural_router/__init__.py` | Exclude `topic` engrams from reranking candidate pool (topics are index nodes, not retrieval content) |
| `memory-service/app/config.py` | HDBSCAN/UMAP params, topic settings |
| `nova-contracts/nova_contracts/engram.py` | Add `topic` to engram type enum |
| `orchestrator/app/tools/memory_tools.py` | Depth parameter on tool definitions, `what_do_i_know` topic-aware path |
| `memory-service/pyproject.toml` | Add `scikit-learn>=1.3`, `umap-learn` |

## Dependencies

- `scikit-learn>=1.3` — HDBSCAN implementation (available in sklearn as of 1.3)
- `umap-learn` — Dimensionality reduction (768-dim -> ~30-dim) before HDBSCAN
- No new infrastructure. Topics are engrams, membership is edges, clustering runs on existing embeddings.

## Migration

- SQL migration to allow `topic` as an engram type if the type column has a CHECK constraint
- Add `topics_created` column to `consolidation_log` table
- No schema changes to `engram_edges` — existing edge types (`part_of`, `instance_of`, `related_to`) cover all needs
