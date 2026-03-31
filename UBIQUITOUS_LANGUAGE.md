# Ubiquitous Language

## Execution

| Term | Definition | Aliases to avoid |
|------|-----------|------------------|
| **Pipeline Task** | An async work unit that flows through a Pod's agent stages via Redis BRPOP queue | "task" (ambiguous), "job", "request" |
| **Chat Task** | A synchronous work unit submitted by a persistent Chat Agent for single-turn completion | "task" (ambiguous), "message" |
| **Pod** | A named configuration preset defining which Pipeline Agents run and in what order | "pipeline config", "agent group" |
| **Quartet** | The default Pod: Context, Task, Guardrail, Code Review (4 stages) | "the pipeline" (imprecise) |
| **Pipeline Agent** | A named stage within a Pod that processes a Pipeline Task at a specific position | "agent" (ambiguous), "step", "phase" |
| **Chat Agent** | A persistent, long-lived conversational entity with identity, config, and memory across sessions | "agent" (ambiguous), "bot", "assistant" |
| **Session** | A WebSocket connection lifetime that maps a client to a Chat Agent via Redis | "connection", "thread" |
| **Conversation** | A user-facing chat history container with ordered messages, stored in PostgreSQL | "chat", "thread", "session" (different concept) |
| **Sandbox Tier** | A security boundary controlling what filesystem/shell access a Pipeline Task gets: workspace, nova, host, or isolated | "permission level", "access mode" |

## Autonomy (Cortex)

| Term | Definition | Aliases to avoid |
|------|-----------|------------------|
| **Goal** | A user-set persistent objective that Cortex autonomously pursues through iterative Pipeline Tasks | "task" (different concept), "mission", "objective" |
| **Drive** | An internal motivational system (serve, maintain, improve, learn, reflect) that evaluates urgency and competes to win each Cycle | "instinct", "motivation", "goal" (different concept) |
| **Stimulus** | An event pushed to the `cortex:stimuli` Redis queue that triggers Drive re-evaluation | "event", "signal", "trigger", "notification" |
| **Cycle** | One iteration of the Cortex thinking loop: drain stimuli, evaluate Drives, execute winning Drive's action | "tick", "loop iteration", "heartbeat" |
| **Maturation Status** | The execution phase of a Goal: triaging, scoping, speccing, review, building, verifying | "status" (that's lifecycle), "stage" |
| **Reflection** | A structured learning record attached to a Goal capturing what was tried, the outcome, and the lesson | "log", "note", "journal entry" (different concept) |
| **Journal Entry** | A Cortex Cycle log recording the action taken, winning Drive, and budget status | "reflection" (different concept), "log entry" |
| **Recommendation** | An intel-derived suggestion for Nova to adopt a new capability, graded A/B/C | "suggestion", "idea", "proposal" |

## Memory (Engram Network)

| Term | Definition | Aliases to avoid |
|------|-----------|------------------|
| **Engram** | An atomic unit of structured knowledge (fact, episode, entity, preference, procedure, schema, goal, self_model, topic) stored with a vector embedding | "memory" (that's the system), "fact", "node" |
| **Engram Edge** | A weighted, typed relationship between two Engrams (caused_by, related_to, contradicts, etc.) | "link", "connection", "association" |
| **Spreading Activation** | Graph-traversal retrieval that seeds by cosine similarity then propagates through weighted Engram Edges | "search", "retrieval", "lookup" |
| **Working Memory** | A curated context window assembled from five slot tiers (pinned, sticky, refreshed, sliding, expiring) with token budgeting | "context", "prompt context", "memory buffer" |
| **Consolidation** | A background "sleep cycle" with 6 phases that strengthens, prunes, and reorganizes the Engram network | "cleanup", "maintenance", "GC" |
| **Self-Model** | A pinned Engram always present in Working Memory that represents Nova's understanding of its own identity and capabilities | "system prompt", "identity" |
| **Neural Router** | A learned ML re-ranker (PyTorch) that improves retrieval relevance after 200+ labeled observations | "reranker", "router" (overloaded) |
| **Source** | A provenance record linking an Engram back to where the knowledge originated (chat, feed, crawl, etc.) with trust scoring | "origin", "reference" |

## Intelligence

| Term | Definition | Aliases to avoid |
|------|-----------|------------------|
| **Feed** | A polled external content stream (RSS, Reddit JSON, GitHub trending/releases, page change) managed by intel-worker | "source" (different concept), "subscription" |
| **Knowledge Source** | A user-curated external resource (web crawl, GitHub profile, social profile) crawled by knowledge-worker | "feed" (different concept), "source" (ambiguous) |
| **Content** | A specific item extracted from a Feed or Knowledge Source, deduplicated and queued for Engram ingestion | "article", "post", "item" |
| **Worker** | A background service that polls/crawls without LLM agency (intel-worker, knowledge-worker) | "agent" (Workers are not Agents) |

## Pipeline Verdicts

| Term | Definition | Aliases to avoid |
|------|-----------|------------------|
| **Guardrail Finding** | A safety issue detected during pipeline execution, typed (prompt_injection, pii_exposure, credential_leak, spec_drift, harmful_content, policy_violation) and severity-rated | "warning", "error", "flag" |
| **Code Review Verdict** | The outcome of the code review Pipeline Agent: pass, needs_refactor, or reject | "result", "decision" (overloaded) |

## Relationships

- A **Pod** contains one or more **Pipeline Agents**, each at a specific position
- A **Pipeline Task** executes within exactly one **Pod**, flowing through its **Pipeline Agents** in order
- A **Chat Agent** submits **Chat Tasks** to the orchestrator for single-turn processing
- A **Session** maps a WebSocket client to exactly one **Chat Agent**
- A **Chat Agent** can have many **Conversations**, each containing ordered messages
- A **Goal** is pursued by **Cortex** through one or more **Pipeline Tasks** (linked via `goal_tasks`)
- A **Drive** evaluates its urgency each **Cycle** and competes to win execution
- A **Stimulus** triggers **Drive** re-evaluation by entering the Cortex queue
- A **Reflection** belongs to exactly one **Goal** and records one attempt's outcome
- An **Engram** connects to other **Engrams** via typed **Engram Edges**
- **Working Memory** assembles **Engrams** into a token-budgeted context for agent use
- **Consolidation** operates on the **Engram** network during idle periods
- A **Feed** produces **Content** items via intel-worker polling
- A **Knowledge Source** produces **Content** items via knowledge-worker crawling
- All **Content** flows into the Engram ingestion queue for decomposition into **Engrams**
- Every **Engram** links back to a **Source** record for provenance tracking

## Example Dialogue

> **Dev:** "When a user creates a new Goal, what happens?"
> **Domain expert:** "Cortex emits a `GOAL_CREATED` Stimulus. On the next Cycle, the Drives re-evaluate — typically the `serve` Drive wins because there's a new Goal to pursue. It dispatches a Pipeline Task to the Quartet Pod."
>
> **Dev:** "So the Goal creates a Task?"
> **Domain expert:** "A *Pipeline Task*, yes — linked via `goal_tasks`. Not a Chat Task. The Goal's Maturation Status starts at `triaging` and advances through `scoping`, `speccing`, `review`, `building`, `verifying` as successive Pipeline Tasks complete."
>
> **Dev:** "And the Pipeline Agents process it?"
> **Domain expert:** "Right. The Quartet has four Pipeline Agents — Context, Task, Guardrail, Code Review. Each runs in sequence. If the Code Review Verdict is `reject`, a Decision Pipeline Agent escalates. The Pipeline Task status moves through `context_running` → `task_running` → `guardrail_running` → `code_review_running` → `complete`."
>
> **Dev:** "Where does memory fit in?"
> **Domain expert:** "The Context Pipeline Agent calls memory-service to build Working Memory — it assembles relevant Engrams into the five slot tiers with token budgets. After the Pipeline Task completes, the exchange gets pushed to the Engram ingestion queue for decomposition into new Engrams."

## Flagged Ambiguities

- **"task"** is used for three distinct concepts: Pipeline Task (async pipeline work unit), Chat Task (sync agent work unit), and Goal-linked task (pipeline task with `goal_id`). **Recommendation:** Always qualify — "Pipeline Task" or "Chat Task". Never use bare "task" in code comments, docs, or UI labels.

- **"agent"** means both Pipeline Agent (a stage in a Pod) and Chat Agent (a persistent conversational entity). **Recommendation:** Always qualify — "Pipeline Agent" or "Chat Agent". The intel-worker and knowledge-worker are "Workers", never "agents".

- **"source"** appears in two domains: Source (Engram provenance record in memory-service) and Knowledge Source (crawled external resource in orchestrator). **Recommendation:** Use "Source" only for Engram provenance. Use "Knowledge Source" for the crawler concept.

- **"status" vs "maturation_status"** on Goals are orthogonal dimensions. A Goal can be `active` (status) and `speccing` (maturation_status) simultaneously. **Recommendation:** Always specify which dimension — "goal status" vs "maturation status". Never say "the goal's status is speccing".

- **"memory"** is used generically for the whole memory-service system, but the atomic unit is an Engram. **Recommendation:** Use "Engram" for individual knowledge nodes, "memory" only when referring to the system/service abstractly.

- **"router"** appears as Neural Router (ML re-ranker in memory-service), pipeline router (orchestrator HTTP routing), and LLM routing (gateway strategy). **Recommendation:** Always qualify — "Neural Router", "pipeline router", "LLM routing strategy".

- **"content"** is used generically across intel (`intel_content` table), knowledge (`knowledge_content` table), and conversations. **Recommendation:** Qualify when the domain isn't obvious from context — "intel content", "knowledge content", "conversation messages".

- **Quartet vs Pipeline** — "Quartet" is a specific Pod (4 agents), but the full pipeline mechanism supports 7+ stages including critique and decision agents. **Recommendation:** Use "Quartet" only for the default 4-agent Pod. Use "pipeline" for the generic execution mechanism.
