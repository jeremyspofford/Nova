# Design: Pluggable Memory Backend + Benchmark Harness

**Date:** 2026-04-18
**Status:** DRAFT — pending approval
**Axis:** feature-completeness, agent-quality
**Tracking:** FC-011

## Problem Statement

Nova's engram memory system is ambitious — graph-based retrieval with spreading activation, autonomic decomposition of LLM output, sleep-cycle consolidation, a neural re-ranker, and outcome feedback. Current state: 7,142 engrams, 83,823 edges, ~2,897 of 3,244 topic engrams superseded (dedup is running). Retrieval produces results (~1.5s for 20 engrams), but we have **zero evidence** that retrieval quality is better than simpler alternatives — no benchmark, no ground truth, no A/B.

Meanwhile, every other competing harness (Claude Code, OpenClaw, Cursor) uses a far simpler approach: **user-edited markdown files** the LLM reads and writes through file tools. Nova users frequently ask why we don't just do that.

The honest answer is: **we don't know if engram is earning its complexity.** We built it, it runs, but we've never measured it against anything.

## Goals

1. Formalize a **memory backend interface** that any implementation can satisfy — engram, markdown files, pure vector, or hybrid.
2. Build a **benchmark harness** that scores competing backends on retrieval quality, performance, and operational cost.
3. Ship a **markdown backend** as the first alternative implementation — cheap, transparent, works alongside engram.
4. Use benchmark results to decide: keep engram as-is, simplify it, replace it, or run a hybrid.

## Non-Goals

- We are **not** pre-committing to replace engram. The data may confirm it's worth the complexity.
- We are not replicating Claude Code's memory file format exactly — the interface matters, not the file convention.
- No user-facing UI changes in this pass. Backend selection is admin-config, not a per-turn knob.

## Memory Backend Interface

Any backend must implement six operations. Four required, two optional.

| Operation | Input | Output | Required? |
|---|---|---|---|
| `write` | text, metadata (source_kind, trust, timestamp, author) | memory_id | ✅ |
| `retrieve` | query, token_budget, filters | ranked list of chunks with memory_ids, each carrying relevance score and provenance | ✅ |
| `feedback` | memory_id, outcome_score (−1.0 to +1.0) | ack | ✅ |
| `provenance` | memory_id | source record (where/when/who/trust) | ✅ |
| `consolidate` | — | stats (merged, pruned, resolved) | ⬜ engram-only; markdown = no-op |
| `explain` | memory_id, query | reasoning trace — engram: activation path; markdown: matching lines | ⬜ highly recommended |

Backends register via a small factory. Orchestrator reads `memory.backend` config (runtime-configurable per the no-.env-config principle) and resolves the implementation.

### What the interface deliberately does NOT specify

- **Storage:** Engram uses pgvector; markdown uses files on disk; future backends could use SQLite, LanceDB, MongoDB. The interface doesn't care.
- **Chunking:** Each backend decides how to slice content.
- **Embedding:** Engram embeds; markdown doesn't. Interface is agnostic.
- **Ranking algorithm:** Cosine, BM25, graph traversal, regex — all valid if `retrieve` returns sensibly ranked chunks.

## Markdown Backend — Implementation Shape

Mirror the pattern Claude Code established. Behavior-level description:

**Layout** (on disk, inside the Nova workspace):

```
memory/
├── NOVA.md              # short index file (<200 lines) — always in context
├── <slug>.md            # topic files, one per concept
├── sources/             # downloaded references, caches, attachments
└── .index.json          # keyword + metadata cache for retrieve()
```

**Operations:**

- **write:** LLM decides when to write a memory. Either writes a new `<slug>.md` file or appends to an existing one. Adds/updates an entry in `NOVA.md` (the index). The agent gets the same `Write`/`Edit` tools it would get on any codebase.
- **retrieve:** NOVA.md is always injected (cheap, small). On top of that, `retrieve(query)` runs a keyword-weighted scan of `<slug>.md` files (grep + a simple BM25-style scoring on the `.index.json`), returning top-K relevant file excerpts up to the token budget. No embeddings, no LLM calls.
- **feedback:** Increments/decrements a numeric score in `.index.json` for the file. Low-scored files drop lower in ranking. Never auto-deleted — user deletion is explicit.
- **provenance:** Reads YAML frontmatter at the top of each file (source, created, updated).
- **consolidate:** No-op. Humans curate.
- **explain:** Returns the matching lines and their file path. Highly legible by design.

**Why this shape:**

- **Transparency:** Open the folder, read your memory. Debug by `cat`. Edit by `vim`. No API calls.
- **Git-tracked:** Full history, diff, rollback. Branching memory is trivial.
- **Portable:** Tar the folder, move it to a new install.
- **Cheap:** Zero LLM decomposition calls. Zero embedding calls. Ingestion is a file write.
- **Scaling ceiling:** Works great up to ~2MB / a few hundred files. Past that, the keyword index degrades and grep latency climbs. Past ~10k entries it becomes unusable — which is exactly engram's sweet spot.

This is the inverse failure mode of engram: markdown wins on small curated corpora, loses on large autonomic ones. That's what makes the comparison interesting.

## Benchmark Harness

### Metrics

**Quality (the important ones):**

- **Precision@5, @10** — of K retrieved, how many are relevant per human/LLM judge
- **Recall@20** — of the known-relevant memory set, how many surfaced
- **Task-level win rate** — end-to-end: LLM response judged with vs. without this backend's context; judge is a strong frontier model scoring 0–5
- **Dedup rate** — on a spiked dataset with known duplicates, what % correctly merge
- **Contradiction surfacing** — on known-contradictory pairs, what % does retrieval flag

**Performance:**

- p50 / p95 retrieval latency
- Tokens in returned context (lower = better at equal quality)
- LLM calls per write (markdown=0, engram=several for decomposition)
- Storage bytes per memory

**Operational:**

- Ingest throughput (memories/sec sustainable)
- Freshness (time from write → retrievable)
- Growth curve (quality degradation at 1k / 10k / 100k memories)

### Test Corpus

1. **Jeremy's actual chat + engram history** — anonymized where needed, exported once
2. **Synthetic stress scenarios** injected on top:
   - Recency + specificity: "What did I say about X 30 messages ago"
   - Aggregation: "What's my overall preference on Y"
   - Contradiction: "Did I contradict myself about Z" (pre-seeded contradictions)
   - Scaling: 10k synthetic facts dump

### Comparison Conditions

Five backends race against each other on the same corpus:

1. **Engram** (current production system) — baseline
2. **Markdown files** (Claude Code-style: NOVA.md + topic files + keyword-scored grep)
3. **Pure vector search** (pgvector alone, no graph, no consolidation) — *the critical honesty test*
4. **Hybrid** (markdown for curated/declarative, engram for episodic/autonomic)
5. **Random retrieval** — sanity baseline

Condition 3 is the one that matters most. Engram's complexity is the graph + consolidation + neural router layer. If pure vector search hits 90% of engram's quality at 20% of the cost, the complexity isn't earning its keep. If engram substantially beats it on long-horizon scaling, we've got real evidence the graph matters.

### Decision Criteria

- **Engram wins clearly** → keep it, document why, move on
- **Pure vector wins or ties** → rip out graph + consolidation, ship simpler system
- **Markdown wins on declarative tier + engram on episodic** → build hybrid (likely outcome)
- **Random is within 10% of anything** → the entire memory subsystem isn't pulling weight; deeper rethink

## Phased Plan

| Phase | Deliverable | Effort |
|---|---|---|
| 1 | Memory interface contract + engram adapter conforms to it | S |
| 2 | Markdown backend implementation (including `.index.json` scorer) | M |
| 3 | Benchmark harness: metrics, corpus loader, judge integration | M |
| 4 | Run benchmark, publish results to `docs/designs/benchmarks/` | S |
| 5 | Act on findings — decide keep/simplify/replace/hybrid | varies |

Phases 1–4 are ~2 weeks of focused work. Phase 5 is the interesting one and depends on the data.

## Open Questions

- Where does the hybrid's routing policy live? (Is "this feels declarative" a write-time decision or a read-time union?)
- Should the benchmark judge be Claude Opus, GPT-5, or a consensus of both?
- Do we snapshot Jeremy's current engram state as a frozen corpus, or run benchmarks live against a running system?
- How do we anonymize Jeremy's chat history for benchmarks if he wants to share them publicly?

## Appendix: Why This Matters

Nova is positioned as a platform, not a single AI product. Memory is the most distinctive piece of that positioning — if engram is genuinely better than markdown for autonomous agents, that's a real differentiator. If it isn't, we're carrying architectural complexity for no gain, and we should be honest about it. Either outcome is a win for the project.
