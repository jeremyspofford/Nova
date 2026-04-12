# 11 – Claude Handoff Document

This document is the exact handoff for Claude to implement Nova Suite v1.

## What Claude should do

1. **Read the entire architecture pack** in order within docs/architecture:
   - 00-suite-vision.md
   - 01-capability-map.md
   - 02-04-platform-deployment-subsystems.md
   - 15-16-data-models-and-apis.md
   - 05-nova-lite-spec.md
   - 06-nova-board-spec.md
   - 07-workflow-spec.md
   - 08-state-spec.md
   - 09-implementation-roadmap.md

2. **Render all Mermaid diagrams** from 18-diagrams-mermaid.md to understand the system.

3. **Follow Phase 0 of 09-implementation-roadmap.md** exactly.

4. **Ask clarifying questions** about:
   - specific DB choice (Postgres/SQLite)
   - API framework (FastAPI/Express)
   - frontend framework (React/Svelte/Vue)

## Rules Claude must follow

- **Never change the data models or API contracts** defined in 15-16. Implement exactly as spec’d.
- **Local-first, cloud-optional** for LLMs. Default to local but support cloud.
- **No new subsystems** beyond what’s spec’d. Use n8n/Windmill for workflows.
- **Safety first**: always respect approvals, risk classes, and policy signals.
- **Modular**: each service should be a separate container.
- **Configuration-driven**: tools, workflows, LLM providers configured via files/env vars.

## Success criteria for Phase 0

- Docker Compose starts 1–2 services (API + DB)
- `/health` returns "ok"
- Can POST and GET a task
- Basic schema validation works

## Next after Phase 0

Claude will receive updated instructions for Phase 1 (Nova Board).

---

**Start here:** Implement Phase 0. Show me the Docker Compose and API server code.
