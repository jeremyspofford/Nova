# 09 – Implementation Roadmap

This document outlines a phased plan for implementing Nova Suite based on the architecture pack.

## Phase 0: Foundation (1–2 days)

**Goal:** Get the shared data models, APIs, and basic infrastructure running.

**Deliverables:**
- Core DB schema for `Event`, `Task`, `Run`, `Approval`, `BoardColumn`, `Entity`, `Tool`, `LLMProviderProfile`
- Basic API server with:
  - `/health`
  - `/system/info`
  - CRUD for tasks, events, runs, approvals, entities (basic versions)
- Docker Compose for local development
- Basic health checks

**Success:** Basic API responds with health info and can store/retrieve tasks.

## Phase 1: Nova Board (2–3 days)

**Goal:** Build the human control surface.

**Deliverables:**
- Web UI implementing the 7-column board from 06-nova-board-spec.md
- Task list, detail view, basic filters (status, labels, risk)
- Approval UI with Approve/Deny buttons and context
- Real-time updates via WebSocket or polling
- Basic task mutations (PATCH /tasks/{id})

**Success:** You can see tasks on a board, approve/deny, and watch Nova-lite updates flow through.

## Phase 2: Nova-lite MVP (3–5 days)

**Goal:** Get the agent loop running end-to-end.

**Deliverables:**
- Nova-lite service implementing the execution loop from 05-nova-lite-spec.md
- Event polling and task triage
- LLM provider integration (`POST /llm/route`)
- Tool invocation (`POST /tools/{name}/invoke`)
- Approval checking and request creation
- Task status updates and summaries

**Success:** Nova-lite can turn events into tasks, plan simple actions, invoke tools, and update the board.

## Phase 3: Home Assistant Integration (2–3 days)

**Goal:** Connect the state layer.

**Deliverables:**
- State service implementing 08-state-spec.md
- Home Assistant entity sync (periodic + events)
- Basic HA service tools (light.turn_on, etc.)
- Entity model population

**Success:** Nova Board shows HA entities and state changes; Nova-lite can control lights/scenes.

## Phase 4: Workflow Adapter (2–3 days)

**Goal:** Connect n8n/Windmill.

**Deliverables:**
- Workflow adapter implementing 07-workflow-spec.md
- 3–5 example tools mapped to n8n/Windmill workflows
- Run lifecycle (queued → running → succeeded/failed)
- Webhook callbacks for completion

**Success:** Nova-lite can invoke n8n/Windmill workflows, and results appear on the board.

## Phase 5: Polish and v1 (3–5 days)

**Goal:** Production-ready v1.

**Deliverables:**
- Security hardening (API auth, HTTPS)
- Monitoring and logging
- Configuration management (tools, LLM providers, HA connection)
- Documentation and setup guide
- Basic testing (scenarios from subsystem specs)

**Success:** Full end-to-end: voice → task → approval → workflow → board updates → home actions.

---

## v2 Roadmap (post-v1)

- **Onboarding & Deployment Assistant:** Hardware survey → deployment recommendation → IaC generation
- **Native workflow designer:** Replace n8n/Windmill dependency
- **Multi-user / team support**
- **Advanced LLM routing:** cost/latency/privacy optimization
- **Long-term memory**
- **Mobile app**

## Riskiest assumptions to validate first

1. Can Nova-lite reliably triage and act on Home Assistant events without creating task spam?
2. Are the approval workflows fast enough for daily use?
3. Does the LLM provider abstraction actually route local vs cloud sensibly?

## Estimated total timeline

- v1 MVP: 3–5 weeks of focused implementation
- v2 onboarding: 1–2 weeks additional

This roadmap prioritizes the subsystems you specified while keeping phases small and testable.
